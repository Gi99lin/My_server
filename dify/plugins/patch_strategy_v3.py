"""Third change to the TMS strategy (0.1.2): images come as data URLs in a tool's text.

Dify passes an MCP image to a strategy only as an unsigned /files/ link the plugin cannot fetch, so the TMS also puts
the picture into its text answer as `data:image/...;base64,...`. The strategy takes each such picture out of the text,
gives it to the model after the round's tool answers, and leaves a short marker in the text, so neither the history
nor Dify's logs carry the base64. The image link itself is only forwarded to the user, without the stock placeholder.
"""
from pathlib import Path

m = Path("manifest.yaml").read_text()
assert "version: 0.1.1\n" in m
Path("manifest.yaml").write_text(m.replace("version: 0.1.1\n", "version: 0.1.2\n", 1))

f = Path("strategies/function_calling.py")
s = f.read_text()


def swap(old: str, new: str) -> None:
    global s
    assert s.count(old) == 1, (s.count(old), old[:70])
    s = s.replace(old, new)


# The image-link branch: forward to the user only; the picture reaches the model from the data URL.
swap('''                                    # TMS E4: a tool image reaches the model, not only the user.
                                    try:
                                        image = self._image_from_link(tool_invoke_response)
                                    except Exception as error:  # the model is told, the run goes on
                                        image = None
                                        tool_result += f"Изображение не удалось передать модели: {type(error).__name__}. "
                                    if image is not None:
                                        round_images.append(image)
                                        tool_result += "Изображение приложено следующим сообщением. "
                                        yield tool_invoke_response
                                        continue''',
     '''                                    # TMS E4: the model gets the picture from the data URL in the tool's text
                                    # (Dify's link is unsigned and cannot be fetched); the link goes to the user only.
                                    yield tool_invoke_response
                                    continue''')

# After a tool's messages are read: take data-URL pictures out of the text.
swap('''                        except Exception as e:
                            tool_result = f"tool invoke error: {e!s}"
                        tool_response = {''',
     '''                            tool_result, data_images = self._take_data_images(tool_result)
                            if data_images:
                                round_images.extend(data_images)
                                tool_result += " Изображение приложено следующим сообщением."
                        except Exception as e:
                            tool_result = f"tool invoke error: {e!s}"
                        tool_response = {''')

swap('''    @staticmethod
    def _image_from_link(response: ToolInvokeMessage) -> ImagePromptMessageContent | None:''',
     '''    @staticmethod
    def _take_data_images(text: str) -> tuple[str, list[ImagePromptMessageContent]]:
        """Pictures a tool put into its text as data URLs, and the text with each replaced by a short marker."""
        import re

        images: list[ImagePromptMessageContent] = []

        def take(match: "re.Match[str]") -> str:
            image_format = match.group(1).lower()
            if image_format == "jpg":
                image_format = "jpeg"
            images.append(
                ImagePromptMessageContent(
                    format=image_format,
                    base64_data=match.group(2),
                    mime_type=f"image/{image_format}",
                    filename="",
                    detail=ImagePromptMessageContent.DETAIL.HIGH,
                )
            )
            return "[изображение]"

        cleaned = re.sub(r"data:image/(png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=]+)", take, text or "")
        return cleaned, images

    @staticmethod
    def _image_from_link(response: ToolInvokeMessage) -> ImagePromptMessageContent | None:''')
f.write_text(s)
print("patched v3")
