
import sys
import os
from datetime import datetime, timedelta

# d:/google antigravity/assemblyccv3 폴더를 path에 추가하여 모듈 import 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import SubtitleEntry
from core.utils import reflow_subtitles

def test_reflow():
    entries = [
        SubtitleEntry("[14:21:46] 인도와 또 협정을 맺었고 이런 것들이 의미하는 바가 큽니다 즉"),
        SubtitleEntry("미국과 중국을 제외한 나머지 나라들끼리라도 그러면 자유무역협정 체제를 복원 내지는 조금이라도 해 나가자 하는 것이 새로운 현상으로 대두되고 있습니다 그래서 여기에서 나오는 것이 CPTPP이고 CPTPP와 EU 간의 연계도 지금 이미 논의가 지속되고 있습니다 그래서 저희들로서 도 이러한"),
        SubtitleEntry("WTO"),
        SubtitleEntry("부서진 WHA제에서 우리가 자유무역국가로서 어떻게 할 것인가 고민을 해야 되고 빨리 행동을 취해야 된다고 생각합니다 첫 번째 이슈 국제개발 협력 기본 계획 이번 4 차 계획은"),
        SubtitleEntry("제가 보기에도 부족합니다 그러나"),
        SubtitleEntry("이것은 지금 해 오던 것을 그래도 무상원조를 외교부에서 통합해서 해 보려고 하는 그러한"),
        SubtitleEntry("[14:22:49] 시도가 들어가 있는 것입니다 그런데 그것 플러스 위원님께서 말씀하신 국제기구가 지금 급변하는 상황에서 우리가 어떻게 역할을 할 것인가 첫 번째 이슈 국제개발협력기본계획 이번 4차"),
        SubtitleEntry("계획은"),
        SubtitleEntry("제가 보기에도 부족합니다 그러나"),
        SubtitleEntry("이것은 지금 해 오던 것을 그래도 무상원조를 외교부에서 통합해서 해 보려고 하는"),
        SubtitleEntry("그러한 시도가 들어가 있는 것입니다 그런데 그것 플러스 위원님께서 말씀하신 국제기구가 지금 급변하는 상황에서 우리가 어떻게"),
        SubtitleEntry("큰 역할을 할 것인가 이것은 자원의 문제도 있고 그다음에 프라이오리티 우선 순위의 문제 도 있고 그렇습니다 그래서 깊이 고민 하고 또 위원님 께 별 도로 협의도 드리고 그렇게 하겠습니다"),
        SubtitleEntry("[14:23:28] OD A 전략적인 문제도 잘 말씀드립니다 예 그렇게 하겠습니다 수고하셨습니다 다음은 김건 간사님 질의해 주십시오 외교부장관님 트럼")
    ]
    
    # 임의의 타임스탬프 설정 (테스트용)
    base_time = datetime.now()
    for i, e in enumerate(entries):
        e.timestamp = base_time + timedelta(seconds=i*5)

    print("=== 원본 ===")
    for e in entries:
        print(f"[{e.timestamp.strftime('%H:%M:%S')}] {e.text}")

    reflowed = reflow_subtitles(entries)

    print("\n=== 결과 ===")
    for e in reflowed:
        print(f"[{e.timestamp.strftime('%H:%M:%S')}] {e.text}")

if __name__ == "__main__":
    test_reflow()
