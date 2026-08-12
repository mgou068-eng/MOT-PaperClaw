from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from services.paper_analysis import has_bad_placeholder, quality_gate


class QualityGatePlaceholderTest(unittest.TestCase):
    def test_allows_unknown_as_domain_term(self):
        self.assertFalse(
            has_bad_placeholder(
                "Semantic-Aware Autonomous Exploration for UAVs in Unknown Indoor Environments"
            )
        )
        self.assertFalse(has_bad_placeholder("面向未知室内环境的无人机探索问题"))

    def test_rejects_placeholder_only_values(self):
        for value in ["Unknown", "未知", "单位: 未知", "N/A", "Not provided"]:
            with self.subTest(value=value):
                self.assertTrue(has_bad_placeholder(value))

    def test_quality_gate_accepts_unknown_environment_paper(self):
        info = {
            "title": "Semantic-Aware Autonomous Exploration for UAVs in Unknown Indoor Environments",
            "authors": "Nguyen Duc-Thien, Ngoc Minh Do",
            "institutions": "University of Engineering and Technology, Vietnam National University",
            "date": "2026-06-21",
        }
        analysis = {
            f"q{i}": "该回答围绕未知室内环境中的无人机自主探索，说明问题、方法和实验结论。"
            for i in range(1, 11)
        }
        for i in range(3, 8):
            analysis[f"q{i}"] = (
                "该方法接收连续视频帧和检测结果，先提取目标外观与运动信息，再通过论文定义的核心模块计算跨帧关系。"
                "模块把关系分数输出给数据关联阶段，随后完成检测与已有轨迹的匹配，并更新已匹配轨迹、保留短时未匹配轨迹。"
                "训练阶段使用论文给出的监督约束学习特征，推理阶段按匹配结果输出带有稳定身份编号的轨迹。"
            )
        analysis["flowchart"] = (
            "flowchart LR\nA[视频帧] --> B[检测与特征]\nB --> C[核心模块]\n"
            "C --> D[数据关联]\nD --> E[轨迹更新]\nE --> F[轨迹输出]"
        )
        analysis["glossary"] = "\n".join(
            [f"- 术语{i}：本文方法中的具体作用{i}" for i in range(1, 6)]
        )

        ok, errors = quality_gate(
            info,
            analysis,
            "本文研究语义感知的无人机自主探索问题，面向未知室内环境构建可执行的导航与建图流程。",
            uploaded_images=1,
        )

        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
