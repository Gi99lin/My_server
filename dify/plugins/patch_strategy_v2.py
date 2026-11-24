"""Second change to the TMS strategy (0.1.1): Dify hands an MCP image to the strategy as an image link, not a blob.

The strategy downloads the image from Dify's API by that link and gives it to the model like a blob image.
"""
from pathlib import Path

m = Path("manifest.yaml").read_text()
assert "version: 0.1.0\n" in m
Path("manifest.yaml").write_text(m.replace("version: 0.1.0\n", "version: 0.1.1\n", 1))

f = Path("strategies/function_calling.py")
s = f.read_text()


def swap(old: str, new: str) -> None:
    global s
    assert s.count(old) == 1, (s.count(old), old[:70])
    s = s.replace(old, new)


swap('''                                    ToolInvokeMessage.MessageType.IMAGE_LINK,
                                    ToolInvokeMessage.MessageType.IMAGE,
                                }:
                                    # Extract the file path or URL from the message''',
     '''                                    ToolInvokeMessage.MessageType.IMAGE_LINK,
                                    ToolInvokeMessage.MessageType.IMAGE,
                                }:
                                    # TMS E4: a tool image reaches the model, not only the user.
                                    try:
                                        image = self._image_from_link(tool_invoke_response)
                                    except Exception as error:  # the model is told, the run goes on
                                        image = None
                                        tool_result += f"Изображение не удалось передать модели: {type(error).__name__}. "
                                    if image is not None:
                                        round_images.append(image)
                                        tool_result += "Изображение приложено следующим сообщением. "
                                        yield tool_invoke_response
                                        continue
                                    # Extract the file path or URL from the message''')

swap('''    @staticmethod
    def _image_from_blob(response: ToolInvokeMessage) -> ImagePromptMessageContent | None:''',
     '''    @staticmethod
    def _image_from_link(response: ToolInvokeMessage) -> ImagePromptMessageContent | None:
        """An image link a tool returned (Dify saves a tool's image and passes its signed /files/ link), downloaded
        from Dify's API and returned as prompt content; None when the message carries no link."""
        import os
        import urllib.request

        link = getattr(response.message, "text", None)
        if not isinstance(link, str) or not link:
            return None
        if link.startswith("/files/"):
            link = os.environ.get("DIFY_INNER_API_URL", "http://api:5001").rstrip("/") + link
        if not link.startswith(("http://", "https://")):
            return None
        with urllib.request.urlopen(link, timeout=15) as reply:
            blob = reply.read(8 * 1024 * 1024 + 1)
            header_type = (reply.headers.get("Content-Type") or "").split(";")[0].strip()
        if not blob or len(blob) > 8 * 1024 * 1024:
            raise ValueError("image size")
        meta = response.meta if isinstance(response.meta, dict) else {}
        mime_type = str(meta.get("mime_type") or header_type or "image/png")
        if not mime_type.startswith("image/"):
            raise ValueError("not an image")
        image_format = mime_type.split("/", maxsplit=1)[1].lower()
        if image_format == "jpg":
            image_format = "jpeg"
        return ImagePromptMessageContent(
            format=image_format,
            base64_data=base64.b64encode(blob).decode("ascii"),
            mime_type=mime_type,
            filename="",
            detail=ImagePromptMessageContent.DETAIL.HIGH,
        )

    @staticmethod
    def _image_from_blob(response: ToolInvokeMessage) -> ImagePromptMessageContent | None:''')
f.write_text(s)
print("patched v2")
