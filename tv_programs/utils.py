import httpx
from googletrans import Translator

# Monkey-patch httpx.Client to bypass SSL verification.
# This is necessary for corporate environments with self-signed certificates.

# 1. Save the original Client class
OriginalClient = httpx.Client

# 2. Create a lambda that returns an instance of the original client with verify=False.
#    It accepts and passes on any other arguments.
httpx.Client = lambda **kwargs: OriginalClient(verify=False, **kwargs)

# Now, when Translator internally creates an httpx.Client, it will use our
# pre-configured, unverified instance.
# TODO: Create translator instance only once.
translator = Translator()


def translate_lv_to_eng(text_lv: str) -> str:
    """
    Translate a text from Latvian to English.

    Args:
        text_lv (str): The text to be translated from Latvian.

    Returns:
        str: The translated text in English.
    """
    return translator.translate(
        text_lv,
        src='lv',
        dest='en'
    ).text
