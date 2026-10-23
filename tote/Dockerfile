# Tote — ambiente fixado para reproduzir os mapas de cobertura (M22, waset)
FROM python:3.12.7-slim-bookworm@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 MPLCONFIGDIR=/tmp/mpl
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && pip freeze > /requirements.lock
WORKDIR /saida
