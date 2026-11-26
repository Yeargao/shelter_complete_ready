
"""Validated private care photos, with interchangeable local and S3 storage."""
import base64
from binascii import Error
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, ImageOps

MAX_BYTES = 5 * 1024 * 1024
FORMATS = {'JPEG', 'PNG', 'WEBP'}


def validate(encoded):
    if len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
        raise HTTPException(413, '每張圖片最多 5 MB')
    try:
        content = base64.b64decode(encoded, validate=True)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, '每張圖片最多 5 MB')
        with Image.open(BytesIO(content)) as image:
            if image.format not in FORMATS or image.width * image.height > 8_000_000:
                raise ValueError('unsupported image')
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
            result = BytesIO()
            ImageOps.exif_transpose(image).convert('RGB').save(result, format='JPEG', quality=86)
        return result.getvalue()
    except (Error, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, '僅接受有效的 JPEG、PNG 或 WebP 圖片') from exc


def backend():
    bucket = os.getenv('SHELTER_PHOTO_BUCKET')
    if bucket:
        import boto3
        region = os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or None
        return boto3.client('s3', endpoint_url=os.getenv('SHELTER_PHOTO_ENDPOINT') or None, region_name=region), bucket
    if os.getenv('VERCEL') == '1' or os.getenv('SHELTER_REQUIRE_OBJECT_STORAGE') == '1':
        raise HTTPException(503, '尚未設定持久化照片物件儲存')
    return Path(os.getenv('SHELTER_UPLOAD_DIR') or Path(__file__).parent / 'uploads'), None


def save(content):
    key = f'{uuid4().hex}.jpg'
    store, bucket = backend()
    if bucket:
        store.put_object(Bucket=bucket, Key=key, Body=content, ContentType='image/jpeg')
    else:
        store.mkdir(parents=True, exist_ok=True)
        with (store / key).open('xb') as destination:
            destination.write(content)
    return key


def read(key):
    store, bucket = backend()
    try:
        if bucket:
            with store.get_object(Bucket=bucket, Key=key)['Body'] as body:
                return body.read()
        return (store / key).read_bytes()
    except FileNotFoundError as exc:
        raise HTTPException(404, '找不到照片內容') from exc
