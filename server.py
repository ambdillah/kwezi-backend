import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pymongo import MongoClient
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import conjugation engine for sentence generation
from conjugation_engine import create_sentence_database

# Import database protection system
from database_protection import protect_database, db_protector, check_database_integrity
from stripe_routes import router as stripe_router

app = FastAPI(title="Mayotte Language Learning API")

# Inclure les routes Stripe
app.include_router(stripe_router)

# Add CORS middleware - CONFIGURATION PRODUCTION SÉCURISÉE
# Accepter les requêtes depuis le frontend (APK Android, Preview, et domaine production)
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS", 
    "https://kwezi-backend.onrender.com,https://kwezi-mobile.preview.emergentagent.com,http://localhost:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # Origines spécifiques au lieu de "*"
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Méthodes spécifiques
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = MongoClient(MONGO_URL)
# Use the correct database name from environment variable
DB_NAME = os.getenv("DB_NAME", "shimaoré_app")
db = client[DB_NAME]

# Collections
words_collection = db.words
exercises_collection = db.exercises
user_progress_collection = db.user_progress
sentences_collection = db.sentences
users_collection = db.users

# Debug: Test database connection
try:
    print(f"Connected to database: {DB_NAME}")
    print(f"Collections: {db.list_collection_names()}")
    count = words_collection.count_documents({})
    print(f"Total words in collection: {count}")
except Exception as e:
    print(f"Database connection error: {e}")

# Pydantic models
class Word(BaseModel):
    id: Optional[str] = None
    french: str
    shimaore: str
    kibouchi: str
    category: str  # famille, couleurs, animaux, salutations, nombres
    image_base64: Optional[str] = None
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    difficulty: int = Field(default=1, ge=1, le=3)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Anciens champs audio authentiques (maintenant compatibilité)
    audio_filename: Optional[str] = None
    audio_pronunciation_lang: Optional[str] = None
    audio_note: Optional[str] = None
    audio_source: Optional[str] = None
    has_authentic_audio: Optional[bool] = False
    audio_updated_at: Optional[datetime] = None
    # Nouveaux champs audio duaux - Système restructuré
    shimoare_audio_filename: Optional[str] = None
    kibouchi_audio_filename: Optional[str] = None
    shimoare_has_audio: Optional[bool] = False
    kibouchi_has_audio: Optional[bool] = False
    # Nouveau format (verbes récents, expressions récentes, traditions récentes)
    audio_filename_shimaore: Optional[str] = None
    audio_filename_kibouchi: Optional[str] = None
    dual_audio_system: Optional[bool] = False
    audio_restructured_at: Optional[datetime] = None

class WordCreate(BaseModel):
    french: str
    shimaore: str
    kibouchi: str
    category: str
    image_base64: Optional[str] = None
    image_url: Optional[str] = None
    difficulty: int = Field(default=1, ge=1, le=3)

class Exercise(BaseModel):
    id: Optional[str] = None
    type: str  # "match_word_image", "quiz", "memory"
    content: dict
    difficulty: int = Field(default=1, ge=1, le=3)
    points: int = 10
    created_at: datetime = Field(default_factory=datetime.utcnow)

class UserProgress(BaseModel):
    id: Optional[str] = None
    user_name: str
    exercise_id: str
    score: int
    completed_at: datetime = Field(default_factory=datetime.utcnow)

# Modèles pour le système premium
class User(BaseModel):
    id: Optional[str] = None
    user_id: str  # Identifiant unique généré côté client
    email: Optional[str] = None
    is_premium: bool = False
    premium_expires_at: Optional[datetime] = None
    subscription_type: Optional[str] = None  # "monthly", "yearly"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    words_learned: int = 0
    total_score: int = 0
    streak_days: int = 0
    last_activity_date: Optional[datetime] = None

class UserCreate(BaseModel):
    user_id: str
    email: Optional[str] = None

class UpgradeRequest(BaseModel):
    user_id: str
    subscription_type: str = "monthly"  # "monthly" ou "yearly"

def dict_to_word(word_dict):
    """Convert MongoDB document to Word model"""
    if '_id' in word_dict:
        word_dict['id'] = str(word_dict['_id'])
        del word_dict['_id']
    return Word(**word_dict)

def dict_to_exercise(exercise_dict):
    """Convert MongoDB document to Exercise model"""
    if '_id' in exercise_dict:
        exercise_dict['id'] = str(exercise_dict['_id'])
        del exercise_dict['_id']
    return Exercise(**exercise_dict)

@app.get("/")
async def root():
    return {"message": "Mayotte Language Learning API", "status": "running"}

@app.get("/test-audio")
async def test_audio_page():
    """Page de test des audios authentiques"""
    from fastapi.responses import FileResponse
    return FileResponse("/app/backend/test_audio.html")

@app.get("/api/vocabulary")
async def get_vocabulary(section: str = Query(None, description="Filter by section")):
    """Get vocabulary by section"""
    try:
        # Build query based on section parameter
        query = {}
        if section:
            query["section"] = section
        
        # Execute query
        cursor = words_collection.find(query)
        words = []
        for word_doc in cursor:
            # Convert MongoDB document to dictionary
            word_dict = dict(word_doc)
            if '_id' in word_dict:
                word_dict['id'] = str(word_dict['_id'])
                del word_dict['_id']
            words.append(word_dict)
        
        return words
    except Exception as e:
        print(f"Error in get_vocabulary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/vocabulary/sections")
async def get_vocabulary_sections():
    """Get all available vocabulary sections"""
    try:
        # Get distinct sections from the vocabulary collection
        sections = words_collection.distinct("section")
        return {"sections": sections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/vocabulary/{word_id}")
async def get_word(word_id: str):
    """Get a specific word by ID"""
    try:
        word_doc = words_collection.find_one({"_id": ObjectId(word_id)})
        if not word_doc:
            raise HTTPException(status_code=404, detail="Word not found")
        
        # Convert to dict and replace _id
        word_dict = dict(word_doc)
        word_dict['id'] = str(word_dict['_id'])
        del word_dict['_id']
        
        return word_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/words")
async def get_words(category: str = Query(None, description="Filter by category")):
    """Get words (compatible with frontend expectations) - SORTED ALPHABETICALLY"""
    try:
        # Build query based on category parameter
        query = {}
        if category:
            query["category"] = category
        
        # Execute query with alphabetical sorting by french word
        cursor = words_collection.find(query).sort("french", 1)  # 1 = ascending order
        words = []
        for word_doc in cursor:
            # Convert MongoDB document to dictionary
            word_dict = dict(word_doc)
            if '_id' in word_dict:
                word_dict['id'] = str(word_dict['_id'])
                del word_dict['_id']
            
            words.append(word_dict)
        
        return words
    except Exception as e:
        print(f"Error in get_words: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/audio/{section}/{filename}")
async def get_audio(section: str, filename: str):
    """Serve audio files from assets/audio directory"""
    try:
        from fastapi.responses import FileResponse
        import os
        
        # Construct the file path
        audio_path = f"/app/frontend/assets/audio/{section}/{filename}"
        
        # Check if file exists
        if not os.path.exists(audio_path):
            raise HTTPException(status_code=404, detail=f"Audio file not found: {filename}")
        
        # Return the file
        return FileResponse(
            path=audio_path,
            media_type="audio/m4a",
            filename=filename
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Words endpoints
@app.get("/api/words")
async def get_words(category: Optional[str] = Query(None)):
    """Get all words or filter by category"""
    query = {}
    if category:
        query["category"] = category
    
    words = list(words_collection.find(query))
    return [dict_to_word(word).dict() for word in words]

@app.get("/api/words/{word_id}")
async def get_word(word_id: str):
    """Get a specific word by ID"""
    try:
        word = words_collection.find_one({"_id": ObjectId(word_id)})
        if word:
            return dict_to_word(word).dict()
        raise HTTPException(status_code=404, detail="Word not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid word ID")

@app.get("/api/sentences")
async def get_sentences(difficulty: int = None, tense: str = None, limit: int = 20):
    """
    Récupère les phrases pour le jeu 'construire des phrases'
    Par défaut, retourne un MIX VARIÉ de tous les temps et de TOUS les verbes
    """
    try:
        import random
        
        # Si aucun filtre spécifique, charger un MIX VRAIMENT VARIÉ
        if not difficulty and not tense:
            # Charger TOUTES les phrases disponibles
            all_sentences_cursor = sentences_collection.find({})
            all_sentences = list(all_sentences_cursor)
            
            # Mélanger COMPLÈTEMENT pour avoir des verbes variés
            random.shuffle(all_sentences)
            
            # Prendre seulement le nombre demandé
            sentences = all_sentences[:limit]
            
            # Vérifier qu'on a bien de la variété (différents verbes français)
            # Si on a beaucoup de phrases du même verbe, remélanger
            french_words = [s.get('french', '').split()[0] for s in sentences]
            unique_verbs = len(set(french_words))
            
            # Si moins de 50% de verbes uniques, remélanger jusqu'à avoir de la variété
            attempts = 0
            while unique_verbs < limit * 0.5 and attempts < 5:
                random.shuffle(all_sentences)
                sentences = all_sentences[:limit]
                french_words = [s.get('french', '').split()[0] for s in sentences]
                unique_verbs = len(set(french_words))
                attempts += 1
        else:
            # Construire le filtre si spécifié
            filter_query = {}
            if difficulty:
                filter_query["difficulty"] = difficulty
            if tense:
                filter_query["tense"] = tense
            
            # Récupérer toutes les phrases correspondantes puis mélanger
            all_sentences = list(sentences_collection.find(filter_query))
            random.shuffle(all_sentences)
            sentences = all_sentences[:limit]
        
        # Convertir ObjectId en string
        for sentence in sentences:
            sentence["_id"] = str(sentence["_id"])
        
        return sentences
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/init-sentences")
async def initialize_sentences():
    """Initialize sentences database for the 'Construire des phrases' game"""
    try:
        # Exécuter la création de phrases dans un thread séparé pour éviter les problèmes d'async
        import asyncio
        await asyncio.get_event_loop().run_in_executor(None, create_sentence_database)
        count = sentences_collection.count_documents({})
        return {"message": f"Sentences database initialized successfully with {count} sentences"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/database-status")
async def get_database_status():
    """Get database integrity status and statistics"""
    try:
        is_healthy, message = db_protector.is_database_healthy()
        stats = db_protector.get_database_stats()
        
        return {
            "healthy": is_healthy,
            "message": message,
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create-backup")
async def create_database_backup():
    """Create a manual backup of the database"""
    try:
        backup_path = db_protector.create_backup("manual_api_call")
        if backup_path:
            return {"message": "Backup created successfully", "backup_path": backup_path}
        else:
            raise HTTPException(status_code=500, detail="Failed to create backup")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/emergency-restore")
async def emergency_database_restore():
    """Emergency restore of the authentic database"""
    try:
        if db_protector.emergency_restore():
            return {"message": "Emergency restore completed successfully"}
        else:
            raise HTTPException(status_code=500, detail="Emergency restore failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/words")
async def create_word(word: WordCreate):
    """Create a new word"""
    word_dict = word.dict()
    word_dict["created_at"] = datetime.utcnow()
    result = words_collection.insert_one(word_dict)
   word_dict["id"] = str(result.inserted_id)
    return word_dict
@app.put("/api/words/{word_id}")
async def update_word(word_id: str, word: WordCreate):
    """Update a word"""
    try:
        word_dict = word.dict()
        result = words_collection.update_one(
            {"_id": ObjectId(word_id)},
            {"$set": word_dict}
        )
        if result.matched_count:
            updated_word = words_collection.find_one({"_id": ObjectId(word_id)})
            return dict_to_word(updated_word).dict()
        raise HTTPException(status_code=404, detail="Word not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid word ID")

@app.delete("/api/words/{word_id}")
async def delete_word(word_id: str):
    """Delete a word"""
    try:
        result = words_collection.delete_one({"_id": ObjectId(word_id)})
        if result.deleted_count:
            return {"message": "Word deleted successfully"}
        raise HTTPException(status_code=404, detail="Word not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid word ID")

# Exercises endpoints
@app.get("/api/exercises")
async def get_exercises():
    """Get all exercises"""
    exercises = list(exercises_collection.find())
    return [dict_to_exercise(exercise).dict() for exercise in exercises]

@app.post("/api/exercises")
async def create_exercise(exercise: Exercise):
    """Create a new exercise"""
    exercise_dict = exercise.dict(exclude={"id"})
    exercise_dict["created_at"] = datetime.utcnow()
    result = exercises_collection.insert_one(exercise_dict)
    exercise_dict["id"] = str(result.inserted_id)
    return exercise_dict

# User progress endpoints
@app.get("/api/progress/{user_name}")
async def get_user_progress(user_name: str):
    """Get progress for a specific user"""
    try:
        progress = list(user_progress_collection.find({"user_name": user_name}))
        for p in progress:
            p["id"] = str(p["_id"])
            del p["_id"]
            # Convert datetime to string for JSON serialization
            if "completed_at" in p:
                p["completed_at"] = p["completed_at"].isoformat()
        return progress
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/progress")
async def create_progress(progress: UserProgress):
    """Record user progress"""
    try:
        progress_dict = progress.dict(exclude={"id"})
        progress_dict["completed_at"] = datetime.utcnow()
        result = user_progress_collection.insert_one(progress_dict)
        
        # Create a clean response dict for JSON serialization
        response_dict = {
            "id": str(result.inserted_id),
            "user_name": progress_dict["user_name"],
            "exercise_id": progress_dict["exercise_id"],
            "score": progress_dict["score"],
            "completed_at": progress_dict["completed_at"].isoformat()
        }
        return response_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Badge system endpoints
@app.get("/api/badges/{user_name}")
async def get_user_badges(user_name: str):
    """Get badges for a specific user"""
    try:
        badges_collection = db.user_badges
        user_badges = badges_collection.find_one({"user_name": user_name})
        
        if user_badges:
            user_badges["id"] = str(user_badges["_id"])
            del user_badges["_id"]
            return user_badges.get("badges", [])
        else:
            return []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/badges/{user_name}/unlock/{badge_id}")
async def unlock_badge(user_name: str, badge_id: str):
    """Unlock a badge for a user"""
    try:
        badges_collection = db.user_badges
        
        # Check if user already has badges record
        user_badges = badges_collection.find_one({"user_name": user_name})
        
        if user_badges:
            # User exists, add badge if not already unlocked
            if badge_id not in user_badges.get("badges", []):
                badges_collection.update_one(
                    {"user_name": user_name},
                    {
                        "$push": {"badges": badge_id},
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )
                return {"message": f"Badge {badge_id} unlocked for {user_name}"}
            else:
                return {"message": f"Badge {badge_id} already unlocked"}
        else:
            # Create new user badges record
            badges_collection.insert_one({
                "user_name": user_name,
                "badges": [badge_id],
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            return {"message": f"Badge {badge_id} unlocked for {user_name}"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/{user_name}")
async def get_user_stats(user_name: str):
    """Get comprehensive stats for a user for badge calculations"""
    try:
        # Get user progress
        progress = list(user_progress_collection.find({"user_name": user_name}))
        
        # Calculate basic stats
        total_score = sum(p.get("score", 0) for p in progress)
        completed_exercises = len(progress)
        average_score = total_score / completed_exercises if completed_exercises > 0 else 0
        best_score = max((p.get("score", 0) for p in progress), default=0)
        perfect_scores = len([p for p in progress if p.get("score", 0) >= 100])
        
        # Calculate learning streaks (simplified)
        learning_days = len(set(p.get("completed_at", datetime.utcnow()).date() for p in progress))
        
        return {
            "user_name": user_name,
            "total_score": total_score,
            "completed_exercises": completed_exercises,
            "average_score": round(average_score, 1),
            "best_score": best_score,
            "perfect_scores": perfect_scores,
            "learning_days": learning_days,
            "words_learned": completed_exercises  # Simplified assumption
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Routes audio authentiques
@app.get("/api/audio/famille/{filename}")
async def get_famille_audio(filename: str):
    """Sert un fichier audio famille"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/famille", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio famille non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/nature/{filename}")
async def get_nature_audio(filename: str):
    """Sert un fichier audio nature"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/nature", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio nature non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/nombres/{filename}")
async def get_nombres_audio(filename: str):
    """Sert un fichier audio nombres"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/nombres", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio nombres non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/animaux/{filename}")
async def get_animaux_audio(filename: str):
    """Sert un fichier audio animaux"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/animaux", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio animaux non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/vetements/{filename}")
async def get_vetements_audio(filename: str):
    """Sert un fichier audio vetements"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/vetements", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio vetements non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/maison/{filename}")
async def get_maison_audio(filename: str):
    """Sert un fichier audio maison"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/maison", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio maison non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/tradition/{filename}")
async def get_tradition_audio(filename: str):
    """Sert un fichier audio tradition"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/tradition", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio tradition non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/transport/{filename}")
async def get_transport_audio(filename: str):
    """Sert un fichier audio transport"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/transport", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio transport non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/adjectifs/{filename}")
async def get_adjectifs_audio(filename: str):
    """Sert un fichier audio adjectifs"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/adjectifs", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio adjectifs non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/expressions/{filename}")
async def get_expressions_audio(filename: str):
    """Sert un fichier audio expressions"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/expressions", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio expressions non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/verbes/{filename}")
async def get_verbes_audio(filename: str):
    """Sert un fichier audio verbes"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/verbes", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio verbes non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/salutations/{filename}")
async def get_salutations_audio(filename: str):
    """Sert un fichier audio salutations"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/salutations", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio salutations non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse( file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/couleurs/{filename}")
async def get_couleurs_audio(filename: str):
    """Sert un fichier audio couleurs"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/couleurs", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio couleurs non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/grammaire/{filename}")
async def get_grammaire_audio(filename: str):
    """Sert un fichier audio grammaire"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/grammaire", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio grammaire non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/nourriture/{filename}")
async def get_nourriture_audio(filename: str):
    """Sert un fichier audio nourriture"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/nourriture", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio nourriture non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/corps/{filename}")
async def get_corps_audio(filename: str):
    """Sert un fichier audio corps"""
    import os
    from fastapi.responses import FileResponse
    
    file_path = os.path.join("/app/frontend/assets/audio/corps", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fichier audio corps non trouvé: {filename}")
    
    if not filename.endswith('.m4a'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .m4a sont supportés")
    
    return FileResponse(
        file_path,
        media_type="audio/mp4",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.get("/api/audio/info")
async def get_audio_info():
    """Information sur les fichiers audio disponibles"""
    import os
    
    famille_dir = "/app/frontend/assets/audio/famille"
    nature_dir = "/app/frontend/assets/audio/nature"
    nombres_dir = "/app/frontend/assets/audio/nombres"
    animaux_dir = "/app/frontend/assets/audio/animaux"
    corps_dir = "/app/frontend/assets/audio/corps"
    salutations_dir = "/app/frontend/assets/audio/salutations"
    couleurs_dir = "/app/frontend/assets/audio/couleurs"
    grammaire_dir = "/app/frontend/assets/audio/grammaire"
    nourriture_dir = "/app/frontend/assets/audio/nourriture"
    verbes_dir = "/app/frontend/assets/audio/verbes"
    expressions_dir = "/app/frontend/assets/audio/expressions"
    adjectifs_dir = "/app/frontend/assets/audio/adjectifs"
    vetements_dir = "/app/frontend/assets/audio/vetements"
    maison_dir = "/app/frontend/assets/audio/maison"
    tradition_dir = "/app/frontend/assets/audio/tradition"
    transport_dir = "/app/frontend/assets/audio/transport"
    
    famille_files = []
    nature_files = []
    nombres_files = []
    animaux_files = []
    corps_files = []
    salutations_files = []
    couleurs_files = []
    grammaire_files = []
    nourriture_files = []
    verbes_files = []
    expressions_files = []
    adjectifs_files = []
    vetements_files = []
    maison_files = []
    tradition_files = []
    transport_files = []
    
    if os.path.exists(famille_dir):
        famille_files = [f for f in os.listdir(famille_dir) if f.endswith('.m4a')]
    
    if os.path.exists(nature_dir):
        nature_files = [f for f in os.listdir(nature_dir) if f.endswith('.m4a')]
        
    if os.path.exists(nombres_dir):
        nombres_files = [f for f in os.listdir(nombres_dir) if f.endswith('.m4a')]
        
    if os.path.exists(animaux_dir):
        animaux_files = [f for f in os.listdir(animaux_dir) if f.endswith('.m4a')]
        
    if os.path.exists(corps_dir):
        corps_files = [f for f in os.listdir(corps_dir) if f.endswith('.m4a')]
        
    if os.path.exists(salutations_dir):
        salutations_files = [f for f in os.listdir(salutations_dir) if f.endswith('.m4a')]
        
    if os.path.exists(couleurs_dir):
        couleurs_files = [f for f in os.listdir(couleurs_dir) if f.endswith('.m4a')]
        
    if os.path.exists(grammaire_dir):
        grammaire_files = [f for f in os.listdir(grammaire_dir) if f.endswith('.m4a')]
        
    if os.path.exists(nourriture_dir):
        nourriture_files = [f for f in os.listdir(nourriture_dir) if f.endswith('.m4a')]
        
    if os.path.exists(verbes_dir):
        verbes_files = [f for f in os.listdir(verbes_dir) if f.endswith('.m4a')]
        
    if os.path.exists(expressions_dir):
        expressions_files = [f for f in os.listdir(expressions_dir) if f.endswith('.m4a')]
        
    if os.path.exists(adjectifs_dir):
        adjectifs_files = [f for f in os.listdir(adjectifs_dir) if f.endswith('.m4a')]
        
    if os.path.exists(vetements_dir):
        vetements_files = [f for f in os.listdir(vetements_dir) if f.endswith('.m4a')]
        
    if os.path.exists(maison_dir):
        maison_files = [f for f in os.listdir(maison_dir) if f.endswith('.m4a')]
        
    if os.path.exists(tradition_dir):
        tradition_files = [f for f in os.listdir(tradition_dir) if f.endswith('.m4a')]
        
    if os.path.exists(transport_dir):
        transport_files = [f for f in os.listdir(transport_dir) if f.endswith('.m4a')]
    
    return {
        "service": "Audio API intégré - Système Dual Étendu",
        "famille": {
            "count": len(famille_files),
            "files": sorted(famille_files)
        },
        "nature": {
            "count": len(nature_files),
            "files": sorted(nature_files)
        },
        "nombres": {
            "count": len(nombres_files),
            "files": sorted(nombres_files)
        },
        "animaux": {
            "count": len(animaux_files),
            "files": sorted(animaux_files)
        },
        "corps": {
            "count": len(corps_files),
            "files": sorted(corps_files)
        },
        "salutations": {
            "count": len(salutations_files),
            "files": sorted(salutations_files)
        },
        "couleurs": {
            "count": len(couleurs_files),
            "files": sorted(couleurs_files)
        },
        "grammaire": {
            "count": len(grammaire_files),
            "files": sorted(grammaire_files)
        },
        "nourriture": {
            "count": len(nourriture_files),
            "files": sorted(nourriture_files)
        },
        "verbes": {
            "count": len(verbes_files),
            "files": sorted(verbes_files)
        },
        "expressions": {
            "count": len(expressions_files),
            "files": sorted(expressions_files)
        },
        "adjectifs": {
            "count": len(adjectifs_files),
            "files": sorted(adjectifs_files)
        },
        "vetements": {
            "count": len(vetements_files),
            "files": sorted(vetements_files)
        },
        "maison": {
            "count": len(maison_files),
            "files": sorted(maison_files)
        },
        "tradition": {
            "count": len(tradition_files),
            "files": sorted(tradition_files)
        },
        "transport": {
            "count": len(transport_files),
            "files": sorted(transport_files)
        },
        "endpoints": {
            "famille": "/api/audio/famille/{filename}",
            "nature": "/api/audio/nature/{filename}",
            "nombres": "/api/audio/nombres/{filename}",
            "animaux": "/api/audio/animaux/{filename}",
            "corps": "/api/audio/corps/{filename}",
            "salutations": "/api/audio/salutations/{filename}",
            "couleurs": "/api/audio/couleurs/{filename}",
            "grammaire": "/api/audio/grammaire/{filename}",
            "nourriture": "/api/audio/nourriture/{filename}",
            "verbes": "/api/audio/verbes/{filename}",
            "expressions": "/api/audio/expressions/{filename}",
            "adjectifs": "/api/audio/adjectifs/{filename}",
            "vetements": "/api/audio/vetements/{filename}",
            "maison": "/api/audio/maison/{filename}",
            "tradition": "/api/audio/tradition/{filename}",
            "transport": "/api/audio/transport/{filename}",
            "dual_system": "/api/words/{word_id}/audio/{lang}"
        },
        "total_categories": 16,
        "total_files": len(famille_files) + len(nature_files) + len(nombres_files) + len(animaux_files) + len(corps_files) + len(salutations_files) + len(couleurs_files) + len(grammaire_files) + len(nourriture_files) + len(verbes_files) + len(expressions_files) + len(adjectifs_files) + len(vetements_files) + len(maison_files) + len(tradition_files) + len(transport_files)
    }

# Nouveaux endpoints pour le système audio dual
@app.get("/api/words/{word_id}/audio/{lang}")
async def get_word_audio_by_language(word_id: str, lang: str):
    """
    Récupère l'audio d'un mot dans une langue spécifique
    lang: 'shimaore' ou 'kibouchi'
    """
    if lang not in ['shimaore', 'kibouchi']:
        raise HTTPException(status_code=400, detail="Langue doit être 'shimaore' ou 'kibouchi'")
    
    try:
        # Récupérer le mot - accepter à la fois 'id' (string) et '_id' (ObjectId)
        # Le frontend envoie 'id' comme string, MongoDB stocke '_id' comme ObjectId
        try:
            word_doc = words_collection.find_one({"_id": ObjectId(word_id)})
        except Exception as e:
            # Si conversion ObjectId échoue, chercher par champ 'id' string
            word_doc = words_collection.find_one({"id": word_id})
        
        if not word_doc:
            raise HTTPException(status_code=404, detail=f"Mot non trouvé avec id: {word_id}")
        
        # Vérifier si le système dual est activé
        if not word_doc.get("dual_audio_system", False):
            raise HTTPException(status_code=400, detail="Ce mot n'utilise pas le système audio dual")
        
        # Récupérer le nom du fichier selon la langue - GÉRER LES TROIS FORMATS
        if lang == "shimaore":
            # Format 1: shimoare_audio_filename (anciennes catégories)
            # Format 2: audio_filename_shimaore (nouveaux mots)
            # Format 3: audio_shimaore (format actuel avec chemin, ex: "famille/Mwandzani.m4a")
            audio_path = word_doc.get("audio_shimaore") or word_doc.get("shimoare_audio_filename") or word_doc.get("audio_filename_shimaore")
            has_audio = word_doc.get("shimoare_has_audio", False) or bool(audio_path)
        else:  # kibouchi
            # Format 1: kibouchi_audio_filename (anciennes catégories)
            # Format 2: audio_filename_kibouchi (nouveaux mots)
            # Format 3: audio_kibouchi (format actuel avec chemin, ex: "famille/Havagna.m4a")
            audio_path = word_doc.get("audio_kibouchi") or word_doc.get("kibouchi_audio_filename") or word_doc.get("audio_filename_kibouchi")
            has_audio = word_doc.get("kibouchi_has_audio", False) or bool(audio_path)
        
        if not audio_path:
            raise HTTPException(status_code=404, detail=f"Pas d'audio disponible en {lang} pour ce mot")
        
        # Si audio_path contient un /, c'est le format "categorie/fichier.m4a"
        if "/" in audio_path:
            # Extraire la catégorie et le nom de fichier
            parts = audio_path.split("/")
            audio_category = parts[0]
            filename = parts[1]
        else:
            # C'est juste le nom du fichier
            filename = audio_path
            audio_category = None
        
        # NOUVELLE ARCHITECTURE : Servir depuis Cloudflare R2 (CDN gratuit, performant)
        from fastapi.responses import RedirectResponse
        import urllib.parse
        
        # URL publique R2 Cloudflare
        R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "https://pub-57ccc97df699405084a85ab3bb4ef546.r2.dev")
        
        # Construire l'URL complète du fichier audio sur R2
        # Les fichiers sont stockés avec leur structure complète: categorie/fichier.m4a
        if "/" in audio_path:
            # Le chemin contient déjà la catégorie (ex: "famille/Mwandzani.m4a")
            audio_url = f"{R2_PUBLIC_URL}/{audio_path}"
        else:
            # Juste le nom du fichier, ajouter la catégorie
            word_category = audio_category or word_doc.get("section") or word_doc.get("category", "famille")
            # Encoder le nom de fichier pour gérer les caractères spéciaux
            encoded_filename = urllib.parse.quote(filename)
            audio_url = f"{R2_PUBLIC_URL}/{word_category}/{encoded_filename}"
        
        # Rediriger vers l'URL R2 (le navigateur/APK téléchargera depuis R2)
        # Avantages: CDN mondial, bande passante illimitée gratuite, pas de charge sur Render.com
        return RedirectResponse(
            url=audio_url,
            status_code=307  # Temporary redirect (préserve la méthode GET)
        )
        
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de mot invalide")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/words/{word_id}/audio-info")
async def get_word_audio_info(word_id: str):
    """
    Récupère les informations audio d'un mot (système dual)
    """
    try:
        word_doc = words_collection.find_one({"_id": ObjectId(word_id)})
        if not word_doc:
            raise HTTPException(status_code=404, detail="Mot non trouvé")
        
        return {
            "word": {
                "id": word_id,
                "french": word_doc.get("french"),
                "shimaore": word_doc.get("shimaore"),
                "kibouchi": word_doc.get("kibouchi")
            },
            "dual_audio_system": word_doc.get("dual_audio_system", False),
            "audio": {
                "shimaore": {
                    "has_audio": word_doc.get("has_shimaoré_audio", False),
                    "filename": word_doc.get("audio_shimaoré_filename"),
                    "url": f"/api/words/{word_id}/audio/shimaore" if word_doc.get("has_shimaoré_audio") else None
                },
                "kibouchi": {
                    "has_audio": word_doc.get("has_kibouchi_audio", False),
                    "filename": word_doc.get("audio_kibouchi_filename"),
                    "url": f"/api/words/{word_id}/audio/kibouchi" if word_doc.get("has_kibouchi_audio") else None
                }
            },
            "legacy_audio": {
                "has_authentic_audio": word_doc.get("has_authentic_audio", False),
                "audio_filename": word_doc.get("audio_filename"),
                "audio_pronunciation_lang": word_doc.get("audio_pronunciation_lang")
            }
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de mot invalide")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Routes de téléchargement pour le build
@app.get("/api/download/code")
async def download_code():
    """Télécharger le code de l'application (version finale avec toutes corrections)"""
    file_path = "/app/backend/kwezi-frontend-code-final.tar.gz"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="application/gzip",
            filename="kwezi-frontend-code-final.tar.gz"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")

@app.get("/api/download/audio")
async def download_audio():
    """Télécharger les fichiers audio (version finale - 98.7% couverture)"""
    file_path = "/app/backend/kwezi-audio-final.tar.gz"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="application/gzip",
            filename="kwezi-audio-final.tar.gz"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")

@app.get("/api/download/complete")
async def download_complete():
    """Télécharger l'application complète (code + audios en un seul fichier)"""
    file_path = "/app/backend/kwezi-app-complete.tar.gz"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="application/gzip",
            filename="kwezi-app-complete.tar.gz"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")

@app.get("/api/download/config/app.json")
async def download_app_json():
    """Télécharger le fichier app.json modifié (newArchEnabled: false)"""
    file_path = "/app/backend/downloads/app.json"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="application/json",
            filename="app.json"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")

@app.get("/api/download/config/package.json")
async def download_package_json():
    """Télécharger le fichier package.json modifié (React Native 0.81.4)"""
    file_path = "/app/backend/downloads/package.json"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="application/json",
            filename="package.json"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")


@app.get("/download-config")
async def download_config_page():
    """Page de téléchargement des fichiers de configuration"""
    file_path = "/app/backend/downloads/index.html"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="text/html"
        )
    raise HTTPException(status_code=404, detail=f"Page non trouvée: {file_path}")


@app.get("/api/download/images/icon.png")
async def download_icon():
    """Télécharger l'icône de l'application"""
    file_path = "/app/backend/downloads/images/icon.png"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="image/png",
            filename="icon.png"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")

@app.get("/api/download/images/adaptive-icon.png")
async def download_adaptive_icon():
    """Télécharger l'icône adaptative de l'application"""
    file_path = "/app/backend/downloads/images/adaptive-icon.png"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="image/png",
            filename="adaptive-icon.png"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")


@app.get("/api/download/images/splash-icon.png")
async def download_splash_icon():
    """Télécharger l'icône de splash screen"""
    file_path = "/app/backend/downloads/images/splash-icon.png"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="image/png",
            filename="splash-icon.png"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")


@app.get("/api/download/images/favicon.png")
async def download_favicon():
    """Télécharger le favicon"""
    file_path = "/app/backend/downloads/images/favicon.png"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="image/png",
            filename="favicon.png"
        )
    raise HTTPException(status_code=404, detail=f"Fichier non trouvé: {file_path}")



@app.get("/api/download-server-file")
async def download_server_file():
    """Télécharger le fichier server.py pour GitHub"""
    file_path = "/app/kwezi-backend-deploy/server.py"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            media_type="text/x-python",
            filename="server.py"
        )
    raise HTTPException(status_code=404, detail="Fichier non trouvé")




@app.get("/api/debug/audio/{word_id}/{lang}")
async def debug_audio_route(word_id: str, lang: str):
    """Route de debug pour l'audio"""
    try:
        from bson import ObjectId
        import os
        
        # Log de debug
        print(f"DEBUG: word_id={word_id}, lang={lang}")
        
        # Connexion DB
        mongo_url = os.getenv('MONGO_URL', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_url)
        db = client['shimaoré_app']
        collection = db['vocabulary']
        
        # Récupérer document
        try:
            obj_id = ObjectId(word_id)
        except Exception as e:
            return {"error": f"Invalid ObjectId: {e}"}
            
        word_doc = collection.find_one({"_id": obj_id})
        if not word_doc:
            return {"error": "Document not found"}
        
        # Récupérer filename
        if lang == "shimaore":
            filename = word_doc.get("audio_shimaoré_filename")
            has_audio = word_doc.get("has_shimaoré_audio", False)
        else:
            filename = word_doc.get("audio_kibouchi_filename") 
            has_audio = word_doc.get("has_kibouchi_audio", False)
        
        if not filename or not has_audio:
            return {"error": "No audio configured", "filename": filename, "has_audio": has_audio}
        
        # Vérifier fichier
        file_path = f"/app/frontend/assets/audio/verbes/{filename}"
        file_exists = os.path.exists(file_path)
        file_size = os.path.getsize(file_path) if file_exists else 0
        
        return {
            "word_id": word_id,
            "lang": lang,
            "filename": filename,
            "has_audio": has_audio,
            "file_path": file_path,
            "file_exists": file_exists,
            "file_size": file_size,
            "word_doc": {
                "french": word_doc.get("french"),
                "section": word_doc.get("section")
            }
        }
        
    except Exception as e:
        import traceback
        return {"error": f"Exception: {e}", "traceback": traceback.format_exc()}


@app.get("/api/audio/{word_id}/{lang}")
async def get_audio_file(word_id: str, lang: str):
    """Route audio simplifiée et fonctionnelle"""
    try:
        from pymongo import MongoClient
        from bson import ObjectId
        from fastapi.responses import FileResponse
        from fastapi import HTTPException
        import os
        
        # Validation langue
        if lang not in ["shimaore", "kibouchi"]:
            raise HTTPException(status_code=400, detail="Langue non supportée")
        
        # Connexion DB
        mongo_url = os.getenv('MONGO_URL', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_url)
        db = client['shimaoré_app']
        collection = db['vocabulary']
        
        # Récupérer le mot
        try:
            obj_id = ObjectId(word_id)
        except:
            raise HTTPException(status_code=400, detail="ID invalide")
            
        word_doc = collection.find_one({"_id": obj_id})
        if not word_doc:
            raise HTTPException(status_code=404, detail="Mot non trouvé")
        
        # Récupérer le fichier audio
        if lang == "shimaore":
            filename = word_doc.get("audio_shimaoré_filename")
            has_audio = word_doc.get("has_shimaoré_audio", False)
        else:
            filename = word_doc.get("audio_kibouchi_filename")
            has_audio = word_doc.get("has_kibouchi_audio", False)
        
        if not filename or not has_audio:
            raise HTTPException(status_code=404, detail=f"Pas d'audio {lang}")
        
        # Retourner le fichier
        file_path = os.path.join("/app/frontend/assets/audio", filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Fichier audio introuvable")
        
        return FileResponse(file_path, media_type="audio/m4a")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# SYSTÈME PREMIUM - Endpoints Utilisateurs
# ============================================

from premium_system import (
    create_user, get_user, upgrade_to_premium,
    get_words_for_user, update_user_activity, get_user_stats
)

@app.post("/api/users/register")
async def register_user(user_data: UserCreate):
    """Créer un nouvel utilisateur gratuit"""
    try:
        user = create_user(user_data.user_id, user_data.email)
        # Convertir ObjectId en string
        user["id"] = str(user["_id"])
        del user["_id"]
        return {"success": True, "user": user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/users/{user_id}")
async def get_user_info(user_id: str):
    """Récupérer les informations d'un utilisateur"""
    try:
        user = get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        # Convertir ObjectId en string
        user["id"] = str(user["_id"])
        del user["_id"]
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/users/{user_id}/upgrade")
async def upgrade_user_premium(user_id: str, upgrade_data: UpgradeRequest):
    """Simuler l'achat Premium (POUR TESTS - À remplacer par Stripe en production)"""
    try:
        user = upgrade_to_premium(user_id, upgrade_data.subscription_type)
        # Convertir ObjectId en string
        user["id"] = str(user["_id"])
        del user["_id"]
        
        return {
            "success": True,
            "message": "Upgrade Premium réussi! Bienvenue dans la communauté Premium Kwezi 🎉",
            "user": user
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/users/{user_id}/stats")
async def get_user_statistics(user_id: str):
    """Récupérer les statistiques d'un utilisateur"""
    try:
        stats = get_user_stats(user_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/users/{user_id}/activity")
async def update_activity(user_id: str, words_learned: int = 0, score: int = 0):
    """Mettre à jour l'activité d'un utilisateur"""
    try:
        user = update_user_activity(user_id, words_learned, score)
        # Convertir ObjectId en string
        user["id"] = str(user["_id"])
        del user["_id"]
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint pour récupérer les mots avec le système premium
@app.get("/api/premium/words")
async def get_words_premium(user_id: Optional[str] = None, category: Optional[str] = None):
    """Récupérer les mots avec limitation selon le statut premium"""
    try:
        result = get_words_for_user(user_id, category)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


# Route pour servir le document de vérification HTML
@app.get("/api/verification-document")
async def get_verification_document():
    """Servir le document HTML de vérification du vocabulaire"""
    from fastapi.responses import HTMLResponse
    
    html_file = "/app/VERIFICATION_VOCABULAIRE_COMPLET.html"
    
    if not os.path.exists(html_file):
        raise HTTPException(status_code=404, detail="Document de vérification non trouvé")
    
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    return HTMLResponse(content=html_content)

# Route pour télécharger le fichier CSV
@app.get("/api/verification-csv")
async def download_verification_csv():
    """Télécharger le fichier CSV de vérification"""
    from fastapi.responses import FileResponse
    
    csv_file = "/app/VERIFICATION_VOCABULAIRE_COMPLET.csv"
    
    if not os.path.exists(csv_file):
        raise HTTPException(status_code=404, detail="Fichier CSV non trouvé")
    
    return FileResponse(
        path=csv_file,
        media_type='text/csv',
        filename='VERIFICATION_VOCABULAIRE_COMPLET.csv'
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
