"""Tests for LLMUsageDetector (task 3.13.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.base import TaskInput, TaskOutput
from nit.agents.detectors.llm_usage import (
    LLMUsageDetector,
    LLMUsageLocation,
    LLMUsageProfile,
)


def _extract_profile(output: TaskOutput) -> LLMUsageProfile:
    """Extract LLMUsageProfile from TaskOutput result."""
    result = output.result
    profile = LLMUsageProfile()
    profile.total_usages = result.get("total_usages", 0)
    profile.providers = set(result.get("providers", []))

    for loc_data in result.get("locations", []):
        location = LLMUsageLocation(
            file_path=Path(loc_data["file_path"]),
            line_number=loc_data["line_number"],
            usage_type=loc_data["usage_type"],
            provider=loc_data["provider"],
            function_name=loc_data.get("function_name"),
            endpoint_url=loc_data.get("endpoint_url"),
            context=loc_data.get("context", ""),
        )
        profile.locations.append(location)

    return profile


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    return tmp_path


@pytest.fixture
def detector() -> LLMUsageDetector:
    """Create an LLMUsageDetector instance."""
    return LLMUsageDetector()


class TestLLMUsageDetector:
    """Test suite for LLMUsageDetector."""

    @pytest.mark.asyncio
    async def test_detector_name_and_description(self, detector: LLMUsageDetector) -> None:
        """Test detector metadata."""
        assert detector.name == "LLMUsageDetector"
        assert "LLM" in detector.description or "AI" in detector.description

    @pytest.mark.asyncio
    async def test_empty_project(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test detection on empty project."""
        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert isinstance(profile, LLMUsageProfile)
        assert profile.total_usages == 0
        assert len(profile.providers) == 0

    @pytest.mark.asyncio
    async def test_openai_python_import(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of OpenAI Python SDK import."""
        code = """
import openai

def generate_text(prompt: str) -> str:
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
"""
        file_path = temp_project / "openai_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "openai" in profile.providers
        assert any(
            loc.usage_type == "import" and loc.provider == "openai" for loc in profile.locations
        )

    @pytest.mark.asyncio
    async def test_anthropic_typescript_import(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of Anthropic TypeScript SDK import."""
        code = """
import Anthropic from '@anthropic-ai/sdk';

async function generateText(prompt: string): Promise<string> {
  const client = new Anthropic({
    apiKey: process.env.ANTHROPIC_API_KEY,
  });

  const response = await client.messages.create({
    model: 'claude-3-5-sonnet-20241022',
    max_tokens: 1024,
    messages: [{ role: 'user', content: prompt }],
  });

  return response.content[0].text;
}
"""
        file_path = temp_project / "anthropic_client.ts"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "anthropic" in profile.providers

    @pytest.mark.asyncio
    async def test_ollama_import(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test detection of Ollama SDK import."""
        code = """
from ollama import Client

def chat(message: str) -> str:
    client = Client(host='http://localhost:11434')
    response = client.chat(model='llama2', messages=[
        {'role': 'user', 'content': message}
    ])
    return response['message']['content']
"""
        file_path = temp_project / "ollama_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "ollama" in profile.providers

    @pytest.mark.asyncio
    async def test_gemini_import(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test detection of Google Gemini SDK import."""
        code = """
import google.generativeai as genai

def generate_content(prompt: str) -> str:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    return response.text
"""
        file_path = temp_project / "gemini_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "gemini" in profile.providers

    @pytest.mark.asyncio
    async def test_litellm_import(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test detection of LiteLLM import."""
        code = """
from litellm import completion

def generate_text(prompt: str, model: str = "gpt-3.5-turbo") -> str:
    response = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
"""
        file_path = temp_project / "litellm_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "litellm" in profile.providers

    @pytest.mark.asyncio
    async def test_http_endpoint_detection(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of HTTP calls to LLM endpoints."""
        code = """
import requests

def call_openai(prompt: str) -> str:
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    return response.json()["choices"][0]["message"]["content"]
"""
        file_path = temp_project / "http_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "openai" in profile.providers
        assert any(
            loc.usage_type == "http_call" and loc.endpoint_url is not None
            for loc in profile.locations
        )

    @pytest.mark.asyncio
    async def test_prompt_template_detection(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of prompt template files."""
        prompts_dir = temp_project / "prompts"
        prompts_dir.mkdir()

        (prompts_dir / "summarize.txt").write_text("Summarize the following text:\n\n{text}")
        (prompts_dir / "translate.md").write_text(
            "# Translation Prompt\n\nTranslate to {language}:\n{text}"
        )

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages >= 2
        assert any(loc.usage_type == "prompt_template" for loc in profile.locations)

    @pytest.mark.asyncio
    async def test_multiple_providers(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test detection of multiple LLM providers in same project."""
        openai_code = "import openai\n\ndef foo(): pass"
        anthropic_code = "import anthropic\n\ndef bar(): pass"

        (temp_project / "openai_client.py").write_text(openai_code)
        (temp_project / "anthropic_client.py").write_text(anthropic_code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages >= 2
        assert "openai" in profile.providers
        assert "anthropic" in profile.providers

    @pytest.mark.asyncio
    async def test_skip_node_modules(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test that node_modules is skipped during scanning."""
        node_modules = temp_project / "node_modules"
        node_modules.mkdir()
        (node_modules / "some_package.js").write_text("import openai from 'openai';")

        # Also create a real file
        (temp_project / "real_client.py").write_text("import openai")

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        # Should only detect the real file, not files in node_modules directory
        # Check that none of the detected files are inside a node_modules directory
        for loc in profile.locations:
            assert "node_modules" not in Path(loc.file_path).parts

    @pytest.mark.asyncio
    async def test_skip_venv(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test that .venv is skipped during scanning."""
        venv = temp_project / ".venv"
        venv.mkdir()
        (venv / "lib" / "openai.py").mkdir(parents=True)
        (venv / "lib" / "openai.py" / "__init__.py").write_text("import openai")

        # Create a real file
        (temp_project / "app.py").write_text("import openai")

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        # Should only detect the real file, not files in .venv directory
        for loc in profile.locations:
            assert ".venv" not in Path(loc.file_path).parts

    @pytest.mark.asyncio
    async def test_context_extraction(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test that context is properly extracted around detected usage."""
        code = """
# Some context before
import openai

def my_function():
    # Function body
    pass
# Some context after
"""
        file_path = temp_project / "test.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert len(profile.locations) > 0
        location = profile.locations[0]
        assert location.context != ""
        assert "import openai" in location.context

    def test_generate_drift_test_candidates(self, detector: LLMUsageDetector) -> None:
        """Test drift test candidate generation (task 3.13.2)."""
        profile = LLMUsageProfile()
        profile.add_location(
            LLMUsageLocation(
                file_path=Path("src/client.py"),
                line_number=5,
                usage_type="import",
                provider="openai",
                context="def generate_text():\n    import openai\n    ...",
            )
        )

        candidates = detector.generate_drift_test_candidates(profile)

        assert len(candidates) > 0
        assert candidates[0]["provider"] == "openai"
        assert "client.py" in candidates[0]["file"]
        assert candidates[0]["suggested_type"] == "semantic"

    def test_generate_drift_test_skeleton(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test drift test skeleton generation (task 3.13.3)."""
        candidates = [
            {
                "name": "OpenAI integration in client.py",
                "file": "src/client.py",
                "line": 10,
                "provider": "openai",
                "function": "generate_text",
                "endpoint": None,
                "suggested_type": "semantic",
            }
        ]

        output_path = temp_project / "drift-tests.yml"
        yaml_content = detector.generate_drift_test_skeleton(candidates, output_path)

        assert output_path.exists()
        assert "version:" in yaml_content
        assert "tests:" in yaml_content
        assert "openai" in yaml_content
        assert "semantic" in yaml_content

    def test_extract_function_name_python(self, detector: LLMUsageDetector) -> None:
        """Test function name extraction from Python code."""
        context = """
def generate_text(prompt: str) -> str:
    import openai
    return openai.complete(prompt)
"""
        name = detector._extract_function_name(context)
        assert name == "generate_text"

    def test_extract_function_name_javascript(self, detector: LLMUsageDetector) -> None:
        """Test function name extraction from JavaScript code."""
        context = """
const generateText = async (prompt) => {
    const response = await openai.complete(prompt);
    return response;
}
"""
        name = detector._extract_function_name(context)
        assert name == "generateText"

    def test_extract_function_name_typescript_function(self, detector: LLMUsageDetector) -> None:
        """Test function name extraction from TypeScript function declaration."""
        context = """
function generateText(prompt: string): Promise<string> {
    return openai.complete(prompt);
}
"""
        name = detector._extract_function_name(context)
        assert name == "generateText"

    def test_extract_function_name_no_match(self, detector: LLMUsageDetector) -> None:
        """Test function name extraction when no function is present."""
        context = "import openai\n# Just an import"
        name = detector._extract_function_name(context)
        assert name is None

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, detector: LLMUsageDetector) -> None:
        """Test handling of non-existent path."""
        task = TaskInput(task_type="llm_detect", target="/nonexistent/path")
        result = await detector.run(task)

        assert len(result.errors) > 0
        assert "does not exist" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_javascript_require_syntax(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of CommonJS require syntax."""
        code = """
const openai = require('openai');

function chat(prompt) {
    return openai.complete(prompt);
}
"""
        file_path = temp_project / "client.js"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "openai" in profile.providers

    @pytest.mark.asyncio
    async def test_azure_openai_endpoint(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of Azure OpenAI endpoints."""
        code = """
import requests

response = requests.post(
    "https://myresource.openai.azure.com/openai/deployments/gpt4/completions",
    headers={"api-key": api_key}
)
"""
        file_path = temp_project / "azure_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "azure_openai" in profile.providers

    @pytest.mark.asyncio
    async def test_huggingface_transformers(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of HuggingFace transformers."""
        code = """
from transformers import pipeline

def generate(prompt):
    generator = pipeline('text-generation', model='gpt2')
    return generator(prompt)
"""
        file_path = temp_project / "hf_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "huggingface" in profile.providers

    @pytest.mark.asyncio
    async def test_prompt_file_in_subdirectory(
        self, detector: LLMUsageDetector, temp_project: Path
    ) -> None:
        """Test detection of prompt files in nested directories."""
        prompts_dir = temp_project / "src" / "llm" / "prompts"
        prompts_dir.mkdir(parents=True)

        (prompts_dir / "system.txt").write_text("You are a helpful assistant.")

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert any(loc.usage_type == "prompt_template" for loc in profile.locations)

    @pytest.mark.asyncio
    async def test_cohere_import(self, detector: LLMUsageDetector, temp_project: Path) -> None:
        """Test detection of Cohere SDK import."""
        code = """
import cohere

co = cohere.Client(api_key)
response = co.generate(prompt="Hello")
"""
        file_path = temp_project / "cohere_client.py"
        file_path.write_text(code)

        task = TaskInput(task_type="llm_detect", target=str(temp_project))
        result = await detector.run(task)
        profile = _extract_profile(result)

        assert profile is not None
        assert profile.total_usages > 0
        assert "cohere" in profile.providers
