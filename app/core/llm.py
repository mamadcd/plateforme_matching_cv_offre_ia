from langchain_core.messages import AIMessage
from app.core.config import settings


class LocalFallbackLLM:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        last_message = messages[-1]
        text = getattr(last_message, "content", str(last_message))
        response = {
            "matches": [
                {
                    "job_id": "fallback-job-1",
                    "job_title": "Fallback Match",
                    "score": 86,
                    "explanation": "Aucune clé API n'est configurée. Le prototype a utilisé un fallback local de matching basé sur les mots-clés détectés dans le CV.",
                    "strengths": ["Cadre technique cohérent", "Mots-clés clairement présents"],
                    "gaps": ["Pas d'analyse LLM externe effectuée"],
                }
            ]
        }

        if "python" in text.lower() and "sql" in text.lower():
            response["matches"][0]["job_title"] = "Data Scientist"
            response["matches"][0]["score"] = 92
        elif "react" in text.lower() or "javascript" in text.lower():
            response["matches"][0]["job_title"] = "Frontend Engineer"
            response["matches"][0]["score"] = 90

        return AIMessage(content=str(response).replace("'", '"'))


def get_llm():
    if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=0.2,
            max_tokens=2000,
        )
    if settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0.2,
            max_tokens=2000,
        )
    if settings.LLM_PROVIDER == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            return LocalFallbackLLM()

        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            temperature=0.1,
            format="json",
            keep_alive=0,
            num_thread=settings.OLLAMA_NUM_THREAD,
        )

    return LocalFallbackLLM()
