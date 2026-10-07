import sys, types, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
fake = types.ModuleType("app.llm")
fake.ask_json = lambda *a: {}
sys.modules["app.llm"] = fake
from app.agents.planner import parse_costar
from app.agents import creative_director as cd
from app.agents.compositor import compose, logo_file

class CampaignChecks(unittest.TestCase):
    def test_multiple_goals_per_scene(self):
        self.assertEqual(cd._goal_ids({"goal_indices": [0, "1", 2]}), {0,1,2})
        self.assertEqual(cd._goal_ids({"goal_index": "3"}), {3})
    def test_costar(self):
        fields = parse_costar("Context: Awareness and access to care\nObjective: Instagram and LinkedIn\nStyle: Brand kit\nTone: Professional\nAudience: Anyone\nResponse: Image")
        self.assertEqual(fields["context"], "Awareness and access to care")
        self.assertEqual(fields["objective"], "Instagram and LinkedIn")
        self.assertEqual(len(fields), 6)

    def test_missing_logo(self):
        with self.assertRaises(ValueError):
            logo_file({"brand_logo_path": "missing-logo.png"})

    def test_render(self):
        for size in [(1080,1080),(1080,1350),(1920,1080)]:
            result = compose(Image.new("RGB",size,"#aabbaa"),
                "Care and Support for Every Family", "Meaningful care begins with understanding", {})
            self.assertEqual(result.size, size)
            inset = max(16, int(size[0] * .035))
            self.assertNotEqual(result.getpixel((inset + 2, inset + 2)), (170,187,170))
        result.save(Path(__file__).parent / "composition-check.png")

    def test_goals_and_review(self):
        brief = {"composition":"Connected scenes","topic_visual_direction":"Access and support",
                 "central_visual":"Community","avoid":[],
                 "scenes":[dict(action="Consultation", setting="Office", meaning="Access",placement="left",goal_index=i%2)
                           for i in range(3)]}
        with patch.object(cd,"ask_json",side_effect=[brief, {"approved":True,"issues":[]}]):
            result=cd.creative_director_node({"user_prompt":"An activity with two goals",
                     "campaign_plan":{"communication_goals":["Access","Support"]}})
            self.assertIn("Consultation",result["image_prompt"])
        brief["scenes"]=[dict(s,goal_index=0) for s in brief["scenes"]]
        with patch.object(cd,"ask_json",return_value=brief):
            with self.assertRaises(ValueError):
                cd.creative_director_node({"campaign_plan":{"communication_goals":["Access","Support"]}})

if __name__ == "__main__":
    unittest.main()
