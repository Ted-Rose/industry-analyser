"""news Django views — only article_audio survives the React
cutover; every other page is the /news/ SPA backed by
/api/news/ ops in news/api.py."""
import os

from django.http import FileResponse, Http404

from .models import NewsArticleAudio


def article_audio(request, pk):
    """Audio seam for a future TTS feature: serve a ready
    NewsArticleAudio's file_path when it exists on disk. No
    generator fills the table yet, so this 404s today — the
    URL contract is what matters."""
    audio = (
        NewsArticleAudio.objects
        .filter(article_id=pk, status='ready')
        .exclude(file_path='')
        # Several engines/voices may be ready — newest wins.
        .order_by('-created_at', '-pk')
        .first()
    )
    if audio is None or not os.path.isfile(audio.file_path):
        raise Http404('No ready audio for this article')
    return FileResponse(open(audio.file_path, 'rb'))
