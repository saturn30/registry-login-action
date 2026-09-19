# Registry login action

GitHub OIDC로 Infisical에서 비밀번호를 가져오고, Tailscale에 연결한 뒤 사설 컨테이너 레지스트리에 로그인한다.
각 앱은 이미지 빌드 후 이 액션을 호출하고 같은 job에서 docker push를 실행하면 된다.
GitHub Secret이나 Infisical 접속용 고정 토큰을 레포마다 등록할 필요가 없다.

## 사용

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
    env:
      IMAGE: registry.deer-deneb.ts.net/my-app:${{ github.sha }}
    steps:
      - uses: actions/checkout@v4
      - run: docker build --tag "$IMAGE" .
      - uses: saturn30/registry-login-action@v1
      - run: docker push "$IMAGE"
```

`my-app`과 Dockerfile 위치는 앱에 맞춰 변경한다. 인증에 시간이 걸리는 동안 Tailscale이 연결된 상태를
최소화하도록 빌드를 먼저 한다. 베이스 이미지가 사설 레지스트리에 있으면 빌드 전에 로그인해야 한다.
이 액션은 빌드, push 또는 Kubernetes 배포를 자동 실행하지 않는다.

## 같은 job에서 환경변수 재사용

**이 액션을 호출한 뒤에는 같은 job의 이후 step에서 Infisical Secret을 환경변수로 사용할 수 있다.**
`uses` 자체의 기능이 아니라, 내부 Infisical 액션을 `export-type: env`로 실행하기 때문이다.
`github-ci` 프로젝트의 `prod` 환경에서 루트(`/`) Secret을 모두 가져오며, 하위 폴더와 import는 포함하지 않는다.

예를 들어 루트에 `DOCKER_REGISTRY_PASSWORD`와 `MANIFEST_UPDATE_TOKEN`을 저장했다면,
공통 액션을 한 번 호출한 후 두 값을 모두 사용할 수 있다. 별도의 output 연결이나 GitHub Secret 등록은 필요 없다.

| 사용하는 위치 | 참조 방법 |
| --- | --- |
| 이후 `run` step의 Bash | `$MANIFEST_UPDATE_TOKEN` |
| 이후 액션의 `with` 입력 | `${{ env.MANIFEST_UPDATE_TOKEN }}` |
| GitHub Secrets | `${{ secrets.MANIFEST_UPDATE_TOKEN }}`로 자동 등록되지는 않음 |

기존 태그 workflow의 `jobs` 아래에 두는 GitOps job 예제:

```yaml
update-gitops-manifest:
  runs-on: ubuntu-latest
  permissions:
    contents: read
    id-token: write
  steps:
    - name: Load shared CI environment and login
      uses: saturn30/registry-login-action@v1

    - name: Checkout infrastructure repository
      uses: actions/checkout@v4
      with:
        repository: bluesoft9999/netcup-infra
        token: ${{ env.MANIFEST_UPDATE_TOKEN }}
        path: netcup-infra

    # 이후 step에서 매니페스트 수정·커밋·push를 수행한다.
```

- 환경변수는 액션 호출 이후 같은 job에서만 유지된다. `needs`로 연결해도 다른 job에 전달되지 않으므로 그 job에서도 액션을 호출한다.
- 다음 workflow 실행에서는 Infisical 값을 다시 가져온다. 실행 중 값이 자동 갱신되거나 runner 밖에 영구 저장되는 것은 아니다.
- 이 액션을 호출하는 job에는 루트의 모든 Secret이 전달된다. `MANIFEST_UPDATE_TOKEN`도 예외가 아니다.
- 환경변수가 필요한 job에서도 현재 액션을 호출하면 Tailscale 연결과 Docker 로그인까지 함께 수행한다. 호출 조건은 아래와 동일하다.
- Secret 값을 확인하려고 `echo`나 `printenv`로 출력하지 않는다.

## 호출 조건

- Linux runner에서 Docker CLI/daemon을 사용할 수 있어야 한다.
- 호출 workflow에 `id-token: write` 권한이 필요하다.
- 호출하는 앱 저장소의 owner는 `saturn30` 또는 `bluesoft9999`다.
- 실행 ref는 `refs/tags/v*`여야 한다. 이벤트 종류는 검사하지 않으므로 해당 태그를 대상으로 수동 실행해도 된다.
- 호출한 job 종료 시 Docker login/Tailscale 액션의 post 처리로 로그아웃한다.
- 다른 job으로 넘어가면 인증 상태가 전달되지 않는다. 그 job에서도 액션을 호출한다.

## 중앙 설정

| 항목 | 값 |
| --- | --- |
| 레지스트리 | registry.deer-deneb.ts.net |
| 레지스트리 계정 | ci-push |
| Infisical 프로젝트 / 환경 / 경로 | github-ci / prod / / |
| 비밀번호 키 | DOCKER_REGISTRY_PASSWORD |
| Infisical Identity ID | 8d988eed-4b7b-460a-a1c9-1b682b1e2336 |
| Infisical Audience | github-ci |
| Tailscale 태그 | tag:ci-registry |

Tailscale Client ID와 Audience는 호출 저장소의 owner에 따라 action.yml에서 자동 선택한다.
Infisical과 Tailscale의 서버 측 OIDC 설정에도 owner 및 ref 제한이 있어야 한다.
액션의 사전 검사는 서버 측 권한 검사를 대신하지 않는다.

이 저장소에는 공개 식별자만 포함한다. 비밀번호는 Infisical에 보관한다.
Infisical 액션은 CI 전용 프로젝트의 루트 값을 환경변수로 전달하므로 해당 프로젝트에는 CI에 허용한 값만 둔다.
액션 저장소가 공개여도 허용되지 않은 GitHub 저장소는 서버 측 인증을 통과할 수 없다.

## 출력

`registry` 출력은 `registry.deer-deneb.ts.net`이다.
사용할 때 액션 step에 `id: registry`를 지정하고 `${{ steps.registry.outputs.registry }}`로 읽을 수 있다.

## 버전과 검증

`@v1`은 호환되는 수정 사항을 받는 주요 버전 태그다. 고정하려면 특정 릴리스 태그나 커밋 SHA를 사용한다.
중첩된 외부 액션은 검토한 커밋 SHA로 고정한다.

인증 검증 workflow는 수동 실행 전용이다. GitHub CLI에서:

```sh
gh workflow run verify.yml --repo saturn30/registry-login-action --ref v1
```

검증은 실제 Infisical OIDC, Tailscale 연결, Docker 로그인 및 기존 이미지 manifest 조회를 수행한다.
테스트 이미지 verification/cuda가 레지스트리에 있어야 한다. 이미지를 생성하거나 삭제하지 않는다.

GitOps 토큰도 확인하려면 `verify-gitops` 입력을 포함한 최신 workflow가 들어 있는 `v*` 태그에서
해당 입력을 `true`로 실행한다. Infisical의 `MANIFEST_UPDATE_TOKEN`으로
`bluesoft9999/netcup-infra` checkout과 `git push --dry-run`을 확인한다. 이 모드에서는
기존 CUDA 테스트 이미지 조회를 건너뛰므로 해당 이미지의 보존 여부에 의존하지 않는다.
토큰 값은 출력하지 않으며 실제 브랜치 생성·매니페스트 변경·배포는 수행하지 않는다.
dry-run은 push 인증 확인이며, main 브랜치 보호 규칙을 통과하는 실제 쓰기까지 검증한 것은 아니다.
