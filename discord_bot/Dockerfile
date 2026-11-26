# Fonts for names in every script, copied from Debian's Noto package (bold sans only, ~7 MB)
FROM debian:bookworm-slim AS fonts
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-core \
    && mkdir /noto && cp /usr/share/fonts/truetype/noto/NotoSans*-Bold.ttf \
       /usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf \
       /usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf /noto/

FROM python:3.12-slim

# Print logs immediately (otherwise stdout is buffered inside Docker and errors show up late or never)
ENV PYTHONUNBUFFERED=1

# libfribidi0: lets Pillow shape right-to-left text (Arabic, Hebrew)
# fonts-wqy-microhei: Chinese/Japanese/Korean names
RUN apt-get update && apt-get install -y --no-install-recommends libfribidi0 fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*
COPY --from=fonts /noto /usr/local/share/fonts/noto

WORKDIR /bot

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
