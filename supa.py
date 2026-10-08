"""Тонкая обёртка над REST и Storage API Supabase (ключ сервера: secret или service_role)."""
from io import BytesIO
import requests
from PIL import Image, ImageOps

BUCKET = 'inspection-photos'


class SupaError(Exception):
    def __init__(self, status, text):
        super().__init__(f'Supabase {status}: {text[:300]}')
        self.status = status
        self.text = text

    @property
    def is_unique_violation(self):
        return self.status == 409 or '23505' in self.text


class Supa:
    def __init__(self, url, key):
        self.url = (url or '').rstrip('/')
        self.key = key or ''
        self.rest = f'{self.url}/rest/v1'
        self.storage = f'{self.url}/storage/v1'

    def _auth(self):
        # Новые ключи (sb_secret_...) — только в apikey; старые JWT — в обоих заголовках
        headers = {'apikey': self.key}
        if not self.key.startswith('sb_'):
            headers['Authorization'] = f'Bearer {self.key}'
        return headers

    def _check(self, resp, ok=(200, 201, 204)):
        if resp.status_code not in ok:
            raise SupaError(resp.status_code, resp.text)
        return resp

    # ---------- таблицы ----------
    def select(self, table, params):
        r = requests.get(f'{self.rest}/{table}', params=params, headers=self._auth(), timeout=15)
        return self._check(r).json()

    def insert(self, table, rows):
        headers = {**self._auth(), 'Content-Type': 'application/json', 'Prefer': 'return=representation'}
        r = requests.post(f'{self.rest}/{table}', json=rows, headers=headers, timeout=15)
        return self._check(r).json()

    def update(self, table, params, values):
        headers = {**self._auth(), 'Content-Type': 'application/json', 'Prefer': 'return=representation'}
        r = requests.patch(f'{self.rest}/{table}', params=params, json=values, headers=headers, timeout=15)
        return self._check(r).json()

    def delete(self, table, params):
        r = requests.delete(f'{self.rest}/{table}', params=params, headers=self._auth(), timeout=15)
        self._check(r)

    # ---------- хранилище фото ----------
    def upload(self, path, data, content_type='image/jpeg'):
        headers = {**self._auth(), 'Content-Type': content_type, 'x-upsert': 'true'}
        r = requests.post(f'{self.storage}/object/{BUCKET}/{path}', data=data, headers=headers, timeout=30)
        self._check(r)
        return path

    def download(self, path):
        r = requests.get(f'{self.storage}/object/{BUCKET}/{path}', headers=self._auth(), timeout=30)
        return self._check(r).content

    def remove(self, paths):
        paths = [p for p in paths if p]
        if not paths:
            return
        headers = {**self._auth(), 'Content-Type': 'application/json'}
        r = requests.delete(f'{self.storage}/object/{BUCKET}', json={'prefixes': paths}, headers=headers, timeout=30)
        self._check(r)


def make_thumbnail(img_bytes, max_side=480, quality=78):
    """Превью для сайта, чтобы карточка ТС с десятками фото открывалась быстро."""
    img = ImageOps.exif_transpose(Image.open(BytesIO(img_bytes)))
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    img.thumbnail((max_side, max_side))
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=quality, optimize=True)
    return buf.getvalue()
