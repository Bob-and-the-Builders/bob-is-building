import firebase_admin
from firebase_admin import credentials, firestore

class FirestoreClient:
    _instance = None

    def __new__(cls, key_path="firebasekey.json"):
        if cls._instance is None:
            # Initialize Firebase only once
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
            cls._instance = super(FirestoreClient, cls).__new__(cls)
            cls._instance.db = firestore.client()
        return cls._instance

    def get_db(self):
        return self.db