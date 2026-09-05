# Hyperliquid BTC 시간축 청산 지도 — 자동 누적 패키지

## 기존 화면이 단순했던 이유

- 기존 화면: 추적 지갑 200개, 스냅샷 1회. 시간 변화가 아직 없습니다.
- 참고 이미지 표기: 약 44,600개 계정, 누적 스냅샷 85회.
- 현재가가 약 8만 달러인데 가격 축이 0~22만 달러까지 벌어지면 가까운 청산 구간이 뭉쳐 보입니다.

이 패키지는 실제 데이터를 더 수집하고 누적하는 방식입니다. 과거 청산 물량을 임의로 만들지 않습니다. 지갑을 늘려도 모두 BTC 포지션을 보유하거나 청산가가 있는 것은 아니므로 밀도가 비례해서 증가한다고 보장하지 않습니다.

## 가장 간단한 설치

1. ZIP 압축을 풉니다.
2. GitHub 저장소 루트에 `index.html`, `collector.py`, `.github` 폴더를 모두 올립니다. `.github/workflows/collect.yml`이 반드시 있어야 합니다. ZIP 파일 자체만 올리면 작동하지 않습니다.
3. 저장소 **Settings → Actions → General → Workflow permissions → Read and write permissions**를 선택합니다.
4. **Settings → Pages → Source → GitHub Actions**로 설정합니다.
5. **Actions → Collect and publish liquidation map → Run workflow**를 한 번 실행합니다. 파일은 기본 브랜치에 있어야 합니다.
6. 첫 수집 및 배포가 끝나면 Actions 실행 결과의 배포 주소 또는 Settings → Pages의 주소를 엽니다.

이후에는 브라우저와 PC가 꺼져 있어도 GitHub에서 수집합니다. 실제 계정 연결, 배포 및 자동 수집 시작까지 대신 완료된 상태는 아닙니다. 저장소 정책이 워크플로의 직접 커밋을 막는 경우 정책에 맞는 권한 구성이 필요합니다.

## 기본 설정

| 항목 | 기본값 |
|---|---|
| 추적 대상 | 리더보드 계정 평가액 상위 5,000개 |
| 지갑 선정 | 최초 선정 후 고정; 시점 간 표본 변경 최소화 |
| 자동 수집 | 2시간마다 실행 요청 |
| 대상 시장 | Hyperliquid 기본 BTC 무기한 |
| 가격 구간 | 고정 $250 |
| 원본 저장 | USD 명목액 및 BTC 수량 |
| 첫 화면 | 현재가 기준 ±15% |
| 색상 | 로그 강도: 작은 물량도 확인 가능 |
| 가격선 | Hyperliquid 5분봉 종가; 없으면 수집 시점 중간가 |
| 기록 보관 | 최근 180회, 정상적으로 하루 12회면 약 15일 |
| 요청 | 주소별 clearinghouseState, 최대 4개 동시 실행, 전역 최소 0.35초 간격 |
| 장애 처리 | 429/5xx 백오프, 요청 제한시간, 성공률 90% 미만이면 기존 데이터 유지 |

5,000개 × 0.35초만 계산해도 약 29분이며 네트워크·재시도 시간은 추가됩니다. 실행 주기는 시작 요청 간격이지 완료 보장이 아닙니다. 정상적으로 2시간마다 누적하면 85회까지 약 7일이 필요합니다. 요청 제한이 반복되면 `REQUEST_INTERVAL`을 늘리세요. 다른 API 호출이 같은 IP의 한도를 공유할 수 있습니다.

## 참고 이미지처럼 리더보드 전체를 추적하려면

`.github/workflows/collect.yml`에서 다음 두 곳을 함께 변경합니다.

- `WALLET_LIMIT: '5000'` → `WALLET_LIMIT: '0'`
- `cron: '17 */2 * * *'` → `cron: '17 */6 * * *'`

0은 리더보드에서 받은 주소 전부이며, 계정 수는 조회 시점마다 다릅니다. 44,600개라면 요청 간격만 약 4시간 20분이 필요합니다. 기본 작업 제한은 300분이라 API 지연이 크면 전체 수집이 완료되지 않을 수 있습니다. 안정적인 전수 근접 수집에는 별도 상시 서버·인덱서가 더 적합합니다. 요청 속도를 무작정 높이지 마세요.

리더보드의 모든 주소도 전체 Hyperliquid 계정 목록은 아닙니다. 하위 계정, vault 주소, 리더보드 미포함 계정과 HIP-3 시장까지 자동 탐색하지는 않습니다.

지갑 목록을 새로 선정하려면 워크플로 env에 `REFRESH_WALLETS: '1'`을 한 번 설정해 실행하고 다시 제거합니다. 실행마다 새로 선정하면 시점마다 표본이 바뀝니다. 기록에는 선정 목록의 해시(`rosterHash`)가 들어갑니다.

## 저장되는 파일

- `data/wallets.json`: 고정 추적 주소 목록. 최초 실행 시 생성됩니다.
- `data/history.json`: 실제 시간별 청산 분포. 첫 실행에는 1개입니다.
- `data/latest.json`: 마지막 수집의 지갑별 BTC 포지션, 성공/실패 내역.
- `data/candles.json`: 조회 가능한 5분봉 가격선.

워크플로는 데이터를 저장소에 커밋하고, 표시용 HTML과 데이터만 GitHub Pages로 배포합니다. 공개 저장소와 공개 페이지에 공개 API에서 얻은 지갑 주소·포지션이 게시됩니다.

HTML은 같은 경로의 `data/`를 읽습니다. 페이지가 열려 있으면 5분마다 새 파일을 확인하며 이 읽기는 새로운 포지션 수집이 아닙니다. HTML만 내려받아 열면 브라우저의 수동 지갑 수집 기능을 사용할 수 있지만 자동 누적은 실행되지 않습니다.

`누적 기록 저장`으로 JSON을 별도 보관할 수 있습니다. `스냅샷 열기`로 이전 기록을 불러옵니다. 이전 앱에서 저장한 넓은 가격 구간은 상세 구간으로 복원할 수 없습니다.

## 해석할 때 필요한 구분

- 색은 해당 스냅샷의 청산가 구간에 있는 수량 또는 명목액입니다. 확정된 체결량이 아닙니다.
- 명목액 = `abs(szi) × liquidationPx`. API `positionValue`는 원본 보존합니다.
- 각 지갑은 서로 다른 시각에 조회됩니다. 한 열은 수집 시작~완료 구간의 표본이며 모든 계정을 동일 순간에 찍은 값이 아닙니다. 최신 중간가는 수집 종료 시 조회합니다.
- null/무효 청산가, 0 수량은 제외합니다. 현재가와 방향이 맞지 않는 청산가도 집계에서 제외합니다.
- 로그 색상은 표시 강도를 바꿀 뿐 물량을 늘리지 않습니다. 실제 수량은 툴팁을 확인하세요.
- 화면 구간 수 변경 시 원본 구간의 겹치는 가격 폭으로 재분배하므로 표시 집계는 근사치입니다. 원본 JSON은 고정 $250 합계를 유지합니다.
- 가격선만 과거로 조회한다고 과거 청산 분포가 생기지 않습니다. 수집하지 않은 날의 청산 데이터는 비어 있습니다.

## 검증 범위

Python 문법, HTML 내 JavaScript 문법, 초기 화면·데모 차트 호출, $250 경계 집계, null 제외, 수량·명목액 합계, 연속 기록 누적, 수집 실패 시 이전 데이터 보존을 모의 응답으로 검증했습니다. 사용자 GitHub 계정에서의 실제 예약 실행·5,000개 실수집·배포는 실행하지 않았습니다.

## 공식 자료

- [Hyperliquid Info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Hyperliquid 요청 제한](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- [공개 리더보드 JSON](https://stats-data.hyperliquid.xyz/Mainnet/leaderboard)
- [GitHub Pages 사용자 지정 워크플로](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub 예약 워크플로](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

GitHub 예약 실행은 지연 또는 누락될 수 있고 기본 브랜치의 워크플로가 실행됩니다. 계정·저장소의 이용 조건과 실행 한도에 따라 동작하며, 정확한 실시간 수집 시스템은 아닙니다.
