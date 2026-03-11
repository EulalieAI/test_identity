import io
import os
import json
from dotenv import load_dotenv
from PIL import Image
from pdf2image import convert_from_bytes

from fastapi import FastAPI, File, UploadFile, Depends, Security, HTTPException, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
import google.generativeai as genai

# ==========================================
# 1. CHARGEMENT DES VARIABLES D'ENVIRONNEMENT
# ==========================================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
API_KEY = os.getenv("API_KEY")

if not GEMINI_API_KEY or not API_KEY:
    raise RuntimeError("ERREUR CRITIQUE : Les clés API (GEMINI_API_KEY, API_KEY) sont manquantes dans l'environnement.")

# ==========================================
# 2. CONFIGURATION DE L'IA (GEMINI)
# ==========================================
genai.configure(api_key=GEMINI_API_KEY)
# Utilisation de la version "flash" (très rapide, parfaite pour l'OCR/Vision)
model = genai.GenerativeModel('gemini-flash-latest')

# ==========================================
# 3. CONFIGURATION FASTAPI & CONSTANTES
# ==========================================
app = FastAPI(title="Identity Extraction API with Gemini", version="1.0.0")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
ALLOWED_FORMATS = {"image/jpeg", "image/png", "application/pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 Mo

# --- GESTIONNAIRE D'ERREURS GLOBAL ---
# Permet de forcer toutes les erreurs FastAPI à utiliser ton format JSON personnalisé
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail}
    )

# ==========================================
# 4. FONCTIONS DE SÉCURITÉ ET D'EXTRACTION
# ==========================================
def get_api_key(api_key_header: str = Security(api_key_header)):
    """Vérifie la présence et la validité de la clé API dans le Header."""
    if not api_key_header or api_key_header != API_KEY:
        raise HTTPException(status_code=401, detail="Clé API manquante ou invalide")
    return api_key_header

def extract_with_gemini(image: Image.Image) -> dict:
    """Envoie l'image à Gemini et force une réponse structurée en JSON."""
    prompt = """
    Tu es un expert en extraction de données. Analyse cette image de document.
    Extrais les informations et renvoie-les STRICTEMENT au format JSON.
    
    Règles de formatage :
    - Les dates doivent être au format YYYY-MM-DD.
    - Si une information est illisible, absente du document ou introuvable, mets "Inconnu".
    - "document_type" doit indiquer précisément le type exact du document lu sur l'image (ex: "Carte Nationale d'Identité", "Passeport", "Permis de conduire", "Carte d'assurance", "Carte d'électeur", "Titre de séjour", etc.).
    - "gender" doit être "M" ou "F".
    - "place_of_birth" correspond au lieu, à la ville ou à la commune de naissance.
    - "occupation" correspond au métier ou à l'occupation de la personne (si mentionné sur le document).

    Structure attendue (respecte scrupuleusement ces clés) :
    {
        "document_type": "",
        "first_name": "",
        "last_name": "",
        "gender": "",
        "date_of_birth": "",
        "place_of_birth": "",
        "occupation": "",
        "nationality": "",
        "document_number": "",
        "date_of_issue": "",
        "date_of_expiry": "",
        "issuing_country": ""
    }
    """
    
    # Demande à Gemini de garantir que la réponse est un JSON valide
    response = model.generate_content(
        [prompt, image],
        generation_config={"response_mime_type": "application/json"}
    )
    
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        raise Exception("Erreur de décodage JSON depuis Gemini. La réponse n'était pas un JSON valide.")

# ==========================================
# 5. ENDPOINT PRINCIPAL
# ==========================================
@app.post("/api/v1/identity/extract")
async def extract_identity(
    file: UploadFile = File(None),
    api_key: str = Depends(get_api_key)
):
    """
    Analyse une image ou un PDF de document d'identité et retourne les informations extraites.
    """
    # 1. Vérification : Fichier non fourni
    if not file:
        raise HTTPException(status_code=400, detail="Fichier non fourni")
    
    # 2. Vérification : Format non supporté
    if file.content_type not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="Format non supporté (Uniquement JPEG, PNG ou PDF)")

    try:
        file_bytes = await file.read()
        
        # 3. Vérification : Limite de taille
        if len(file_bytes) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="Fichier trop volumineux (Max 10 Mo)")

        # 4. Préparation de l'image pour l'IA
        pil_image = None
        if file.content_type == "application/pdf":
            images = convert_from_bytes(file_bytes, first_page=1, last_page=1)
            if not images:
                raise HTTPException(status_code=400, detail="Document PDF illisible ou vide")
            pil_image = images[0]
        else:
            pil_image = Image.open(io.BytesIO(file_bytes))

        # 5. Extraction via l'IA
        extracted_data = extract_with_gemini(pil_image)

        # 6. Vérification : Document non reconnu
        if extracted_data.get("last_name") == "Inconnu" and extracted_data.get("first_name") == "Inconnu":
            raise HTTPException(status_code=400, detail="Document illisible, informations introuvables ou format non supporté")

        # 7. Succès
        return {
            "status": "success",
            "data": extracted_data
        }

    except HTTPException:
        # Laisse passer les erreurs HTTP qu'on a créées manuellement (400, 401)
        raise
    except Exception as e:
        # Capture toutes les autres erreurs (IA indisponible, plantage code, etc.)
        raise HTTPException(status_code=500, detail=f"Erreur interne lors du traitement : {str(e)}")