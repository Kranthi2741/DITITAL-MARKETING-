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
    def test_resource_goal_does_not_require_image_scene(self):
        brief = {"composition":"Connected scenes","topic_visual_direction":"Community care",
                 "central_visual":"Support","avoid":[],
                 "scenes":[dict(action="Consultation", setting="Office", meaning="Care",
                                placement="left",goal_indices=[0]) for _ in range(3)]}
        state = {"user_prompt":"Awareness and resources for further information",
                 "campaign_plan":{"visual_goals":["Show supportive care"],
                                  "caption_goals":["Offer resources for further information"],
                                  "delivery_requirements":["Instagram"],
                                  "communication_goals":["Show supportive care",
                                                         "Offer resources for further information"]}}
        with patch.object(cd,"ask_json",side_effect=[brief, {"approved":True,"issues":[]}]) as calls:
            result = cd.creative_director_node(state)
            self.assertEqual(calls.call_count, 2)
            self.assertIn("Consultation", result["image_prompt"])

    def test_planner_preserves_goal_groups(self):
        from app.agents import planner
        plan = {"visual_goals":["Show care"],"caption_goals":["Offer resources"],
                "delivery_requirements":["Instagram"],"objective":"Awareness"}
        with patch.object(planner,"ask_json",return_value={"campaign_plan":plan,"costar":{}}):
            result = planner.planner_node({"user_prompt":"Context: Awareness\nObjective: Instagram"})
        self.assertEqual(result["campaign_plan"]["communication_goals"], ["Show care","Offer resources"])
        self.assertEqual(result["campaign_plan"]["delivery_requirements"], ["Instagram"])

    def test_caption_resource_request_is_checked(self):
        from app.agents import content_agent
        state = {"user_prompt":"Offer resources",
                 "campaign_plan":{"caption_goals":["Offer resources"]}}
        with patch.object(content_agent,"ask_json",side_effect=[
                {"caption":"Ask your care team for reliable information.","hashtags":[]},
                {"approved":True,"issues":[]}]) as calls:
            result = content_agent.content_agent_node(state)
        self.assertIn("care team", result["caption"])
        self.assertIn("Offer resources", calls.call_args.args[1])

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
