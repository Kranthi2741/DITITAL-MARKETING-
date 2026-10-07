import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import sys
import types
# The bundled verification runtime may lack production HTTP dependencies.
# These tests mock transport; they never perform network calls.
try:
    import requests
except ImportError:
    requests = types.ModuleType("requests")
    requests.post = Mock()
    sys.modules["requests"] = requests
try:
    import dotenv
except ImportError:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    sys.modules["dotenv"] = dotenv
from app.llm import evaluate_image
from app.agents.quality_agent import quality_agent_node


class VisionChecks(unittest.TestCase):
    def test_pixels_sent_and_critical_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            path.write_bytes(b"test image bytes")
            response = Mock()
            response.json.return_value = {"message": {"content":
                '{"score": 90, "issues": [], "critical_issues": ["Incorrect equipment"]}'}}
            with patch("app.llm.requests.post", return_value=response) as post, patch(
                    "app.llm.ask_json", return_value={"confirmed_indices": [0]}):
                result = evaluate_image(str(path), {})
                sent = post.call_args.kwargs["json"]["messages"][0]["images"][0]
                self.assertEqual(base64.b64decode(sent), path.read_bytes())
            with patch("app.agents.quality_agent.evaluate_image", return_value=result):
                state = quality_agent_node({"generated_image_path": str(path)})
                self.assertFalse(state["quality_approved"])
                self.assertEqual(state["retry_count"], 1)

    def test_minor_suggestions_pass_at_85(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            path.write_bytes(b"test")
            response = Mock()
            response.json.return_value = {"message": {"content":
                '{"score":85,"issues":[],"critical_issues":["Slight clutter","Slight blur"]}'}}
            with patch("app.llm.requests.post", return_value=response), patch(
                    "app.llm.ask_json", return_value={"confirmed_indices": []}):
                result = evaluate_image(str(path), {})
            with patch("app.agents.quality_agent.evaluate_image", return_value=result):
                state = quality_agent_node({"generated_image_path": str(path)})
            self.assertTrue(state["quality_approved"])
            self.assertEqual(len(state["quality_suggestions"]), 2)
            self.assertEqual(state["quality_rejection_reason"], "")

    def test_score_below_threshold(self):
        with patch("app.agents.quality_agent.evaluate_image",
                   return_value={"score":74,"issues":["Unclear"],"critical_issues":[]}):
            state = quality_agent_node({"generated_image_path":"unused"})
        self.assertFalse(state["quality_approved"])
        self.assertIn("below 75", state["quality_rejection_reason"])

    def test_invalid_review_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            path.write_bytes(b"test")
            response = Mock()
            response.json.return_value = {"message": {"content": '{"score": 99}'}}
            with patch("app.llm.requests.post", return_value=response):
                with self.assertRaises(ValueError):
                    evaluate_image(str(path), {})


if __name__ == "__main__":
    unittest.main()
