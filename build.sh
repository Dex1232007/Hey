#!/usr/bin/env bash
# Install yt-dlp into project root

curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o yt-dlp
chmod +x yt-dlp
mv yt-dlp /usr/local/bin/
