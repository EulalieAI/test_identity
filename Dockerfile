# Utiliser une image Python officielle légère
FROM python:3.10-slim

# Mettre à jour le système et installer poppler-utils (indispensable pour lire les PDF)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Copier le fichier des dépendances
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY main.py .

# Exposer le port sur lequel l'API va tourner
EXPOSE 8000

# Commande pour lancer l'application avec Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]