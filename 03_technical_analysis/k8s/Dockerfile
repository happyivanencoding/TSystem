
FROM python:3.12-slim-trixie 


RUN apt-get update \ 
 && apt-get upgrade -y \
 && apt-get autoremove -y \
 && apt-get clean

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NUMBA_CACHE_DIR=/tmp/numba_cache


# Créer le dossier de travail
WORKDIR /app

# Copier requirements et installer les dépendances
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Copier le code applicatif
COPY . .

# Exposer le port
EXPOSE 8050

# Commande par défaut
CMD ["/bin/bash", "-lc", "mkdir -p \"$NUMBA_CACHE_DIR\" && exec python api.py"]
