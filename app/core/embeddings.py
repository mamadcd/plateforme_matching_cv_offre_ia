from typing import Iterable

from app.core.config import settings


class LocalBgeEmbeddings:
    def __init__(self, model_name: str = settings.EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed_query(self, text: str):
        vector = self.model.encode([text], normalize_embeddings=True)
        return vector[0].tolist()

    def embed_documents(self, texts: Iterable[str]):
        text_list = list(texts)
        if not text_list:
            return []
        vectors = self.model.encode(text_list, normalize_embeddings=True)
        return vectors.tolist()


def get_embeddings():
    return LocalBgeEmbeddings(settings.EMBEDDING_MODEL)
