"""Image processing and Cloudflare R2 storage."""

import base64
import io
import os
import time

import boto3
import requests
from PIL import Image, ImageFilter


def generate_blur_base64(image_bytes: bytes) -> str:
    """Compress image to 20px wide with Gaussian blur, return as base64 data URI."""
    img = Image.open(io.BytesIO(image_bytes))
    # Resize to 20px wide, maintaining aspect ratio
    width, height = img.size
    new_height = int(height * (20 / width))
    img = img.resize((20, new_height), Image.LANCZOS)
    # Apply Gaussian blur
    img = img.filter(ImageFilter.GaussianBlur(radius=5))
    # Convert to JPEG bytes
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=60)
    b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64_str}"


def _get_r2_client():
    """Create and return a boto3 S3 client configured for Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def upload_to_r2(image_bytes: bytes, article_id: str) -> str:
    """Upload original image to Cloudflare R2 and return public URL."""
    bucket_name = os.environ["R2_BUCKET_NAME"]
    public_domain = os.environ["R2_PUBLIC_DOMAIN"]

    # Convert to WebP for better compression
    img = Image.open(io.BytesIO(image_bytes))
    # Force full decode now so we don't upload partially decoded bytes.
    img.load()
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="WEBP", quality=90)
    webp_bytes = buffer.getvalue()

    key = f"{article_id}.webp"

    client = _get_r2_client()
    client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=webp_bytes,
        ContentType="image/webp",
    )

    return f"https://{public_domain}/{key}"


def download_image(url: str) -> bytes | None:
    """Download image from URL and return bytes."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BeaconBot/1.0)"}
    last_err: Exception | None = None

    for attempt in range(1, 4):
        try:
            resp = requests.get(url, timeout=45, headers=headers, stream=True)
            resp.raise_for_status()

            expected_len = resp.headers.get("Content-Length")
            buf = io.BytesIO()
            for chunk in resp.iter_content(chunk_size=1024 * 128):
                if chunk:
                    buf.write(chunk)
            data = buf.getvalue()

            if expected_len is not None:
                try:
                    expected = int(expected_len)
                    if expected > 0 and len(data) != expected:
                        raise IOError(
                            f"incomplete download: got {len(data)} bytes, expected {expected}"
                        )
                except ValueError:
                    # Ignore invalid Content-Length
                    pass

            # Validate the image can be fully decoded (catches truncated files).
            img = Image.open(io.BytesIO(data))
            img.load()

            return data

        except Exception as e:
            last_err = e
            wait_s = 0.6 * attempt
            print(f"[storage] Download attempt {attempt} failed for {url}: {e}")
            time.sleep(wait_s)

    print(f"[storage] Failed to download image from {url}: {last_err}")
    return None


def process_image(image_url: str, article_id: str) -> tuple[str, str] | None:
    """Download image, generate blur placeholder, upload to R2.

    Returns (r2_image_url, base64_blur) or None on failure.
    """
    image_bytes = download_image(image_url)
    if not image_bytes:
        return None

    base64_blur = generate_blur_base64(image_bytes)
    r2_url = upload_to_r2(image_bytes, article_id)

    return r2_url, base64_blur
