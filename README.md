# Registry login and GitOps actions

Infisical의 `github-ci / prod / /`를 공통 CI 환경으로 사용한다. 앱마다 GitHub Secret을 등록하지 않는다.

| 호출 | 역할 |
| --- | --- |
| `saturn30/registry-login-action/load-env@v1` | 환경변수만 로딩. Tailscale·Docker 로그인 없음 |
| `saturn30/registry-login-action@v1` | Tailscale 연결과 Docker 로그인. 환경변수가 없으면 먼저 로딩 |
| `saturn30/registry-login-action/update-manifests@v1` | 이미지 태그 갱신·커밋·push. 앞에서 load-env 호출 필요 |

## 이미지 게시

주소는 Infisical의 `DOCKER_REGISTRY_HOST`에서 읽는다. 값은 `https://`나 경로 없이 호스트만 저장한다.

```yaml
name: Publish image
on:
  push:
    tags: ['v*']
permissions:
  contents: read
  id-token: write
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: saturn30/registry-login-action/load-env@v1
      - name: Set image name
        env:
          REPOSITORY: ${{ github.repository }}
          TAG: ${{ github.ref_name }}
        run: echo "IMAGE=$DOCKER_REGISTRY_HOST/${REPOSITORY,,}:$TAG" >> "$GITHUB_ENV"
      - run: docker build --tag "$IMAGE" .
      - uses: saturn30/registry-login-action@v1
      - run: docker push "$IMAGE"
```

빌드 중에는 Tailscale에 연결하지 않는다. 로그인 액션은 이미 로딩된 host/password가 있으면 Infisical을 다시 호출하지 않는다.
사설 베이스 이미지가 필요하면 빌드 전에 로그인한다. 기존처럼 루트 액션만 호출하는 방식도 계속 지원한다.
루트 액션의 `registry` output은 Infisical에서 읽은 호스트다.

## 이미지 게시 후 배포

이미지를 모두 게시한 job 뒤에 다음 job을 둔다. `needs`의 job 이름과 앱 경로·이미지 목록만 맞춘다.

```yaml
deploy:
  needs: publish
  runs-on: ubuntu-latest
  permissions:
    contents: read
    id-token: write
  steps:
    - uses: saturn30/registry-login-action/load-env@v1
    - uses: saturn30/registry-login-action/update-manifests@v1
      with:
        manifest-path: argo/manifests/my-app
        images: |
          ${{ env.DOCKER_REGISTRY_HOST }}/saturn30/my-app
```

이 job은 GitHub와 Infisical만 사용한다. Tailscale·Docker에 연결하지 않는다.
별도 deploy 입력이나 활성화 변수 없이 이미지 게시 성공 후 GitOps 갱신을 실행한다.

| 입력 | 값 |
| --- | --- |
| `manifest-path` | 인프라 저장소 안의 매니페스트 디렉터리. 필수 |
| `images` | 레지스트리를 포함한 **태그 없는 전체 이미지 이름**, 줄마다 하나. 필수 |
| `repository` | 기본 `bluesoft9999/netcup-infra` |
| `branch` | 기본 `main` |

태그는 호출한 workflow의 Git 태그에서 자동으로 가져온다. 예를 들어 `v1.2.3` 실행은 각 이미지를 `:v1.2.3`으로 갱신한다.
Python 설치 환경과 YAML 파서는 액션이 준비한다. 앱에 스크립트·requirements를 복사할 필요가 없다.

- 지정한 디렉터리의 Git 추적 `.yaml`·`.yml` 파일만 처리한다.
- Deployment·StatefulSet·DaemonSet·Job·CronJob의 containers와 initContainers를 지원한다.
- 이미지의 레지스트리·저장소 이름을 정확히 비교해 태그 또는 digest를 새 태그로 바꾼다. 같은 이미지를 쓰는 migration Job도 함께 갱신한다.
- 입력한 이미지 중 하나라도 없거나 YAML이 잘못되면 파일을 쓰기 전에 실패한다.
- 다른 이미지·환경변수·pull Secret은 유지한다. OCIR 전환 같은 일회성 정리는 수행하지 않는다.
- 변경 파일의 YAML 서식과 주석은 PyYAML 직렬화로 정규화된다. 변경 없는 파일은 다시 쓰지 않는다.
- 변경이 없으면 커밋하지 않는다. 동시 push 충돌은 rebase 후 최대 세 번 push하며, 실제 충돌이면 실패한다. 강제 push는 하지 않는다.
- 호스트를 바꾸면 기존 매니페스트의 이미지 이름도 새 레지스트리로 이전해야 한다. 다른 호스트의 이미지를 추측해서 바꾸지 않는다.

## 환경변수와 인증

Infisical `github-ci / prod / /`에 저장한다.

| 키 | 용도 |
| --- | --- |
| `DOCKER_REGISTRY_HOST` | 레지스트리 호스트. 선택적으로 포트 포함 |
| `DOCKER_REGISTRY_PASSWORD` | 레지스트리 `ci-push` 계정 비밀번호 |
| `MANIFEST_UPDATE_TOKEN` | 인프라 저장소 읽기·쓰기 PAT |

**load-env 또는 루트 로그인 액션 이후 같은 job의 모든 step에서 환경변수가 유지된다.**
Infisical 액션의 `export-type: env`로 루트 Secret 전체를 가져온다. 하위 폴더와 import는 포함하지 않는다.
`run`에서는 `$DOCKER_REGISTRY_HOST`, 액션의 `with`에서는 `${{ env.DOCKER_REGISTRY_HOST }}`를 사용한다.
`${{ secrets.* }}`로 GitHub Secret에 자동 등록되는 것은 아니다.

job 간에는 전달되지 않으므로 각 job에서 load-env를 호출한다. 다음 실행 때 다시 읽으며 실행 중 자동 갱신하지 않는다.
값을 확인하기 위해 `echo`나 `printenv`로 Secret을 출력하지 않는다.

현재 OIDC 조건은 Linux runner, owner `saturn30` 또는 `bluesoft9999`, ref `refs/tags/v*`다.
호출 job에 `id-token: write`가 필요하다. Infisical·Tailscale 서버 측 신뢰 조건도 같은 범위를 허용해야 한다.
공개 저장소의 코드를 호출할 수 있다는 것이 Secret 접근 권한을 의미하지는 않는다.

Infisical Identity ID는 `8d988eed-4b7b-460a-a1c9-1b682b1e2336`, audience는 `github-ci`다.
Tailscale client는 caller owner에 따라 선택하고 `tag:ci-registry`로 연결한다.
job 종료 시 내부 액션의 post 처리로 Docker 로그아웃과 Tailscale 정리를 수행한다.

## 버전과 검증

`v1`은 검증 후 갱신하는 주요 버전 태그다. 재현하려면 릴리스 태그나 커밋 SHA로 고정한다.
루트 액션 내부 load-env 참조도 검증된 SHA로 고정하므로 load-env 구현을 바꿀 때 그 참조를 함께 갱신한다.

```sh
python3 -m pip install -r update-manifests/requirements.txt
python3 -m unittest discover -s tests -v
gh workflow run verify.yml --repo saturn30/registry-login-action --ref v1
```

수동 검증은 Infisical 로딩·Tailscale·Docker 로그인 후 인프라 저장소에 임시 브랜치를 만들어
공통 액션의 실제 커밋·push와 재실행 시 커밋 생략을 확인한다. 임시 브랜치는 종료 시 삭제한다.
운영 main, 이미지 게시, 앱 배포는 변경하지 않는다. 임시 브랜치의 workload 이미지 태그는 검증용 값이다.

현재 릴리스는 `v1.1.0`이다. 2026-09-19 [실제 CI 검증](https://github.com/saturn30/registry-login-action/actions/runs/35438702321)에서 환경변수 로딩·로그인·임시 브랜치 갱신·재실행 무변경·임시 브랜치 삭제까지 통과했다.
