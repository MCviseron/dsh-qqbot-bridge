import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
t = p.read_text(encoding='utf-8')


def sub(old, new):
    global t
    assert old in t, 'anchor missing: %r' % old[:70]
    t = t.replace(old, new, 1)


# 1) URL 提取助手
sub('''def _sent_idx(result):''',
    '''def _attachment_url(attachment):
    """Best-effort URL out of one quoted-media attachment."""
    if isinstance(attachment, str):
        return attachment.strip() or None
    if isinstance(attachment, dict):
        for key in ("url", "file_url", "remote_url", "src", "thumb_url"):
            value = attachment.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _sent_idx(result):''')

# 2) 媒体分支收集 URL
sub('''                if isinstance(attachments, list) and attachments:
                    text = ""
                    kind = "image"
                    break''',
    '''                if isinstance(attachments, list) and attachments:
                    text = ""
                    kind = "image"
                    urls = [_attachment_url(item) for item in attachments]
                    quote_urls = [url for url in urls if url][:4]
                    break
                single = _attachment_url(element)
                if single:  # 有的版本把图片地址直接放在元素上
                    text = ""
                    kind = "image"
                    quote_urls = [single]
                    break''')

sub('''        kind = "text"
        text = ""
        ref_idx = ""''',
    '''        kind = "text"
        text = ""
        ref_idx = ""
        quote_urls = []''')

# 3) 返回里带上 urls
sub('''            "outbound": outbound,
            "kind": kind,
        }''',
    '''            "outbound": outbound,
            "kind": kind,
            "urls": list(quote_urls),
        }''')

# 4) 把引用图片并入 images
sub('''    def _quote_author(self, ref_idx):''',
    '''    async def _quote_images(self, quote: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Download the quoted image(s) so the model can actually see them."""
        if not quote or quote.get("kind") != "image":
            return []
        urls = [url for url in (quote.get("urls") or []) if isinstance(url, str) and url]
        if not urls:
            return []
        images, _skipped = await self._collect_images([{"url": url} for url in urls])
        return list(images)

    def _quote_author(self, ref_idx):''')

# 5) 群聊入口：先取 quote，再合并引用图片
sub('''        await self._queue_message(
            conv_key,
            text,
            "主人" if is_owner else f"群友{short_id(member_openid)}",
            is_owner,
            images,
            chat=chat,
            quote=self._quote_of(message),
        )''',
    '''        quote = self._quote_of(message)
        if quote is not None:
            quoted_images = await self._quote_images(quote)
            if quoted_images:
                images = list(images) + quoted_images
        await self._queue_message(
            conv_key,
            text,
            "主人" if is_owner else f"群友{short_id(member_openid)}",
            is_owner,
            images,
            chat=chat,
            quote=quote,
        )''')

# 6) 私聊入口同样
sub('''        await self._queue_message(
            conv_key,
            text,
            "主人" if is_owner else f"用户{short_id(user_openid)}",
            is_owner,
            images,
            quote=self._quote_of(message),
        )''',
    '''        quote = self._quote_of(message)
        if quote is not None:
            quoted_images = await self._quote_images(quote)
            if quoted_images:
                images = list(images) + quoted_images
        await self._queue_message(
            conv_key,
            text,
            "主人" if is_owner else f"用户{short_id(user_openid)}",
            is_owner,
            images,
            quote=quote,
        )''')

p.write_text(t, encoding='utf-8')
print('quoted images wired')
