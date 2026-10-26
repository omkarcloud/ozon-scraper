FROM chetan1111/botasaurus:chrome-151

ENV PYTHONUNBUFFERED=1
# Never open debug prompts/devtools on crash.
ENV ENV=production

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# The image ships real Google Chrome + Xvfb. Chrome only runs for a few
# seconds to pass Ozon's Antibot challenge; every request after that is
# plain HTTP. Ozon often refuses the challenge to Chrome on Linux servers —
# if the container's calls fail with "captcha" / "block", run the scraper on
# your desktop (python run.py) instead.
CMD ["python", "run.py"]
