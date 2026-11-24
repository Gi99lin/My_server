"""Turn a copy of langgenius/agent 0.0.51 into the TMS strategy that passes tool images to the model (E4)."""
from pathlib import Path

m = Path("manifest.yaml").read_text()
m = m.replace("version: 0.0.51\n", "version: 0.1.0\n", 1).replace('author: "langgenius"', 'author: "gigglin"').replace('name: "agent"', 'name: "tms_agent"')
m = m.replace('en_US: "Dify Agent Strategies"', 'en_US: "TMS Agent Strategy"').replace("en_US: Dify official Agent strategies collection", "en_US: Function calling that passes tool images (screenshots) to the model")
Path("manifest.yaml").write_text(m)
p = Path("provider/agent.yaml").read_text()
p = p.replace("author: langgenius", "author: gigglin").replace("  name: agent\n", "  name: tms_agent\n", 1).replace("  - strategies/ReAct.yaml\n", "")
Path("provider/agent.yaml").write_text(p)
y = Path("strategies/function_calling.yaml").read_text()
y = y.replace("  name: function_calling\n", "  name: function_calling_vision\n", 1).replace("    en_US: FunctionCalling\n", "    en_US: FunctionCalling (vision)\n", 1)
Path("strategies/function_calling.yaml").write_text(y)

f = Path("strategies/function_calling.py")
s = f.read_text()


def swap(old: str, new: str) -> None:
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)


# 1. Collect the images a round of tool calls returns.
swap("            # call tools\n            tool_responses = []\n",
     "            # call tools\n            tool_responses = []\n"
     "            # Images that tools returned in this round; they reach the model after all the tool answers (TMS E4).\n"
     "            round_images: list[ImagePromptMessageContent] = []\n")

# 2. A blob that is an image goes to the model instead of the placeholder.
swap('''                                    tool_result += "Generated file ... "
                                    # TODO: convert to agent invoke message
                                    yield tool_invoke_response''',
     '''                                    image = self._image_from_blob(tool_invoke_response)
                                    if image is not None:
                                        round_images.append(image)
                                        tool_result += "Изображение приложено следующим сообщением. "
                                    else:
                                        tool_result += "Generated file ... "
                                    yield tool_invoke_response''')

# 3. After every tool answer of the round, one user message with the round's images.
swap("            # After handling all tool calls, insert a blank line so the next assistant thought",
     '''            if round_images:
                current_thoughts.append(
                    UserPromptMessage(
                        content=[
                            TextPromptMessageContent(data="Изображения из ответов инструментов этого шага:"),
                            *round_images,
                        ]
                    )
                )
            # After handling all tool calls, insert a blank line so the next assistant thought''')

# 4. Keep images in the history for a vision model; clear them only for a model without vision.
swap('''        # Clear images if: model doesn't support vision OR it's not the first iteration
        if not supports_vision or len(current_thoughts) != 0:''',
     '''        # Clear images only for a model without vision; a vision model keeps every screenshot (TMS E4).
        if not supports_vision:''')

# 5. The helper that turns an image blob into prompt content.
swap('''    @staticmethod
    def _to_image_prompt_content(file: File) -> ImagePromptMessageContent:''',
     '''    @staticmethod
    def _image_from_blob(response: ToolInvokeMessage) -> ImagePromptMessageContent | None:
        """An image blob a tool returned (an MCP ImageContent arrives as one), as prompt content; None otherwise."""
        meta = response.meta if isinstance(response.meta, dict) else {}
        mime_type = str(meta.get("mime_type") or "")
        blob = getattr(response.message, "blob", None)
        if not mime_type.startswith("image/") or not isinstance(blob, (bytes, bytearray)) or not blob:
            return None
        image_format = mime_type.split("/", maxsplit=1)[1].lower()
        if image_format == "jpg":
            image_format = "jpeg"
        return ImagePromptMessageContent(
            format=image_format,
            base64_data=base64.b64encode(bytes(blob)).decode("ascii"),
            mime_type=mime_type,
            filename="",
            detail=ImagePromptMessageContent.DETAIL.HIGH,
        )

    @staticmethod
    def _to_image_prompt_content(file: File) -> ImagePromptMessageContent:''')
f.write_text(s)
print("patched")
