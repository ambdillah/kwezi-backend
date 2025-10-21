from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Kwezi API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Connection
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "mayotte_app")

try:
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    print(f"Connected to database: {DB_NAME}")
    print(f"Collections: {db.list_collection_names()}")
except Exception as e:
    print(f"Database connection error: {e}")

@app.get("/")
async def root():
    return {"message": "Kwezi API - Backend pour l'apprentissage du Shimaoré et Kibouchi"}

@app.get("/api/health")
async def health_check():
    try:
        client.admin.command('ping')
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/api/words")
async def get_words(
    limit: int = 50,
    skip: int = 0,
    category: str = None,
    search: str = None
):
    try:
        collection = db["words"]
        query = {}
        
        if category:
            query["category"] = category
        
        if search:
            query["$or"] = [
                {"french": {"$regex": search, "$options": "i"}},
                {"shimaore": {"$regex": search, "$options": "i"}},
                {"kibouchi": {"$regex": search, "$options": "i"}}
            ]
        
        words = list(collection.find(query).skip(skip).limit(limit))
        
        for word in words:
            word["_id"] = str(word["_id"])
        
        total = collection.count_documents(query)
        
        return {
            "words": words,
            "total": total,
            "limit": limit,
            "skip": skip
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sentences")
async def get_sentences(limit: int = 50, skip: int = 0):
    try:
        collection = db["sentences"]
        sentences = list(collection.find().skip(skip).limit(limit))
        
        for sentence in sentences:
            sentence["_id"] = str(sentence["_id"])
        
        total = collection.count_documents({})
        
        return {
            "sentences": sentences,
            "total": total
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/categories")
async def get_categories():
    try:
        collection = db["words"]
        categories = collection.distinct("category")
        return {"categories": sorted(categories)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/exercises")
async def get_exercises():
    try:
        collection = db["exercises"]
        exercises = list(collection.find())
        
        for exercise in exercises:
            exercise["_id"] = str(exercise["_id"])
        
        return {"exercises": exercises}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
