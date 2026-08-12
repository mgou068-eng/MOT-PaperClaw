from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from services.paper_analysis import normalize_glossary, normalize_mermaid_flowchart, summarize_paper


class MethodExplanationTest(unittest.TestCase):
    def test_normalizes_mermaid_fence_and_glossary_bullets(self):
        flowchart = normalize_mermaid_flowchart(
            "```mermaid\nflowchart LR\nA[视频] --> B[检测]\nB --> C[关联]\n```"
        )
        glossary = normalize_glossary("GLOSSARY:\n* 检测：定位目标\n1. 关联：连接身份")

        self.assertTrue(flowchart.startswith("flowchart LR"))
        self.assertNotIn("```", flowchart)
        self.assertEqual(glossary, "- 检测：定位目标\n- 关联：连接身份")

    @patch("services.paper_analysis.call_llm")
    @patch("services.paper_analysis.load_prompt", return_value="{title}\n{authors}\n{abstract_en}\n{pdf_text}")
    def test_summarize_parses_new_teaching_sections(self, _load_prompt, call_llm):
        detailed = (
            "该方法接收连续帧与检测框，先提取外观和运动信息，再由核心时序模块计算跨帧关系。"
            "关系分数被送入数据关联，匹配成功后更新轨迹状态，未匹配轨迹按论文规则保留或终止。"
            "训练阶段学习特征和关联目标，推理阶段输出每个目标带稳定身份编号的完整轨迹。"
            "当目标短时被遮挡时，系统继续维护历史状态，并在目标重新出现后结合时序关系恢复匹配，"
            "从而避免仅凭当前帧外观相似度造成身份交换。输出不仅包含当前目标框，还包含跨帧一致的身份标签；"
            "因此读者可以沿着输入、模块变换、关联决策和轨迹输出逐步检查整个实现，而不只看到抽象结论。"
        )
        answers = "\n".join(f"A{i}: {detailed}" for i in range(1, 11))
        call_llm.return_value = (
            "摘要翻译: 这是一篇关于多目标跟踪方法的中文摘要。\n"
            "FLOWCHART:\n```mermaid\nflowchart LR\nA[视频] --> B[检测]\nB --> C[时序模块]\n"
            "C --> D[数据关联]\nD --> E[轨迹更新]\nE --> F[轨迹输出]\n```\n"
            "GLOSSARY:\n- 检测：定位当前帧目标\n- 轨迹：同一目标的时序状态\n"
            "- 关联：匹配检测和轨迹\n- 外观：描述目标视觉身份\n- 运动：预测目标位置\n"
            f"{answers}"
        )

        analysis = summarize_paper("Test MOT", "A. Author", "English abstract", "Full paper text")

        self.assertEqual(analysis["abstract_zh"], "这是一篇关于多目标跟踪方法的中文摘要。")
        self.assertTrue(analysis["flowchart"].startswith("flowchart LR"))
        self.assertEqual(len(analysis["glossary"].splitlines()), 5)
        self.assertIn("核心时序模块", analysis["q4"])
        call_llm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
