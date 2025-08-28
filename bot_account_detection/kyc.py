import random
import re
import datetime
import string
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import hashlib
import phonenumbers

class KYCStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUIRES_REVIEW = "requires_review"

class DocumentType(Enum):
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    NATIONAL_ID = "national_id"

class KYCLevel(Enum):
    LOW_RISK = 1
    MEDIUM_RISK = 2
    HIGH_RISK = 3
    CRITICAL_RISK = 4

@dataclass
class PersonalInfo:
    first_name: str
    last_name: str
    date_of_birth: str  # DD-MM-YYYY format
    nationality: str
    address: str
    phone: str
    email: str

@dataclass
class Document:
    document_type: DocumentType
    document_number: str
    full_name: str
    issued_date: str
    expiry_date: str
    issuing_country: str

@dataclass
class KYCResult:
    status: KYCStatus
    kyc_level: KYCLevel
    score: int
    flags: List[str]
    verification_date: str

class KYCChecker:
    def __init__(self):
        self.sanctions_list = self._load_sanctions_list()
        self.pep_list = self._load_pep_list()
        self.blacklisted_countries = {'Country ABC', 'Country XYZ'}  # Example countries
        
    def verify_user(self, personal_info: PersonalInfo, documents: List[Document]) -> KYCResult:
        """
        Main KYC verification function
        """
        flags = []
        score = 100  # Start with perfect score and deduct points
        
        # Validate personal information
        personal_flags, personal_score = self._validate_personal_info(personal_info)
        flags.extend(personal_flags)
        score -= personal_score
        
        # Validate documents
        doc_flags, doc_score = self._validate_documents(documents)
        flags.extend(doc_flags)
        score -= doc_score
        
        # Check sanctions and PEP lists
        sanctions_flags, sanctions_score = self._check_sanctions_and_pep(personal_info)
        flags.extend(sanctions_flags)
        score -= sanctions_score
        
        # Determine KYC level and status
        kyc_level = self._calculate_kyc_level(score, flags)
        status = self._determine_status(score, flags, kyc_level)

        return KYCResult(
            status=status,
            kyc_level=kyc_level,
            score=max(0, score),
            flags=flags,
            verification_date=datetime.datetime.now().isoformat(),
        )
    
    def _validate_personal_info(self, info: PersonalInfo) -> Tuple[List[str], float]:
        """Validate personal information fields"""
        flags = []
        score_deduction = 0
        
        # Name validation
        if not self._is_valid_name(info.first_name) or not self._is_valid_name(info.last_name):
            flags.append("Invalid name")
            score_deduction += 10
        
        # Date of birth validation
        if not self._is_valid_date_of_birth(info.date_of_birth):
            flags.append("Invalid date of birth")
            score_deduction += 10
        
        # Phone validation
        if not self._is_valid_phone(info.phone):
            flags.append("Invalid phone number")
            score_deduction += 10
        
        # Check if user is from blacklisted country
        if info.nationality in self.blacklisted_countries:
            flags.append(f"User from sanctioned country: {info.nationality}")
            score_deduction += 50

        # Age verification (must be 18+)
        age = self._calculate_age(info.date_of_birth)
        if age < 18:
            flags.append("User under minimum age requirement")
            score_deduction += 100  # Automatic rejection
        
        return flags, score_deduction
    
    def _validate_documents(self, documents: List[Document]) -> Tuple[List[str], float]:
        """Validate submitted documents"""
        flags = []
        score_deduction = 0
        
        if not documents:
            flags.append("No documents submitted")
            return flags, 50

        required_docs = {DocumentType.PASSPORT, DocumentType.DRIVERS_LICENSE, DocumentType.NATIONAL_ID}
        provided_id_docs = {doc.document_type for doc in documents if doc.document_type in required_docs}
        
        if not provided_id_docs:
            flags.append("No valid ID document provided")
            score_deduction += 50

        # Check document expiry
        valid_doc_date = False
        for doc in documents:
            if valid_doc_date:
                break
            if doc.expiry_date:
                if self._is_document_expired(doc.expiry_date):
                    flags.append(f"Expired {doc.document_type.value}")
                else:
                    valid_doc_date = True
            elif doc.issued_date:
                if self._is_document_outdated(doc.issued_date):
                    flags.append(f"Outdated {doc.document_type.value}")
                else:
                    valid_doc_date = True

        if not valid_doc_date:
            score_deduction += 20
        
        return flags, score_deduction
    
    def _check_sanctions_and_pep(self, info: PersonalInfo) -> Tuple[List[str], float]:
        """Check against sanctions and PEP lists"""
        flags = []
        score_deduction = 0
        
        full_name = f"{info.first_name} {info.last_name}".lower()
        
        # Check sanctions list
        if self._is_on_sanctions_list(full_name):
            flags.append("User found on sanctions list")
            score_deduction += 100  # Automatic rejection
        
        # Check PEP list
        if self._is_politically_exposed(full_name):
            flags.append("Politically Exposed Person (PEP)")
            score_deduction += 30  # Requires enhanced due diligence
        
        return flags, score_deduction

    def _calculate_kyc_level(self, score: float, flags: List[str]) -> KYCLevel:
        """Calculate KYC level based on score and flags"""
        critical_flags = ["User found on sanctions list", "Politically Exposed Person (PEP)"]

        if any(flag in flags for flag in critical_flags):
            return KYCLevel.CRITICAL_RISK
        elif score < 30:
            return KYCLevel.HIGH_RISK
        elif score < 60:
            return KYCLevel.MEDIUM_RISK
        else:
            return KYCLevel.LOW_RISK

    def _determine_status(self, score: float, flags: List[str], risk_level: KYCLevel) -> KYCStatus:
        """Determine KYC status based on various factors"""

        if risk_level == KYCLevel.CRITICAL_RISK or score < 20:
            return KYCStatus.REJECTED
        elif risk_level == KYCLevel.HIGH_RISK or "Politically Exposed Person (PEP)" in flags:
            return KYCStatus.REQUIRES_REVIEW
        elif score >= 60 and risk_level == KYCLevel.LOW_RISK:
            return KYCStatus.APPROVED
        else:
            return KYCStatus.REQUIRES_REVIEW
    
    def _is_valid_name(self, name: str) -> bool:
        """Validate name format"""
        if not name or not re.match(r"^[a-zA-Z\s\-'\.]+$", name.strip()):
            return False
        return True

    def _is_valid_date_of_birth(self, date_str: str) -> bool:
        """Validate date of birth format and reasonableness"""
        try:
            birth_date = datetime.datetime.strptime(date_str, "%d-%m-%Y")
            today = datetime.datetime.now()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return 0 <= age <= 120
        except ValueError:
            return False
    
    def _is_valid_phone(self, phone: str) -> bool:
        """Validate phone number"""
        return phonenumbers.is_possible_number(phonenumbers.parse(phone, None))

    def _calculate_age(self, date_of_birth: str) -> int:
        """Calculate age from date of birth"""
        try:
            birth_date = datetime.datetime.strptime(date_of_birth, "%d-%m-%Y")
            today = datetime.datetime.now()
            return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        except ValueError:
            return 0

    def _is_document_outdated(self, issued_date: str) -> bool:
        """Check if document is outdated (issued more than 5 years ago)"""
        try:
            issued = datetime.datetime.strptime(issued_date, "%d-%m-%Y")
            return (datetime.datetime.now() - issued).days > 5 * 365
        except ValueError:
            return False

    def _is_document_expired(self, expiry_date: str) -> bool:
        """Check if document is expired"""
        try:
            expiry = datetime.datetime.strptime(expiry_date, "%d-%m-%Y")
            return expiry < datetime.datetime.now()
        except ValueError:
            return True  # Assume expired if date format is invalid

    def _is_on_sanctions_list(self, name: str) -> bool:
        """Check if name is on sanctions list"""
        return name in self.sanctions_list
    
    def _is_politically_exposed(self, name: str) -> bool:
        """Check if person is politically exposed"""
        return name in self.pep_list
    
    def _load_sanctions_list(self) -> set:
        """Load sanctions list (mock implementation)"""
        # In a real implementation, this would load from a database or API
        return {
            "john terrorist",
            "elanor criminal",
            "ethan badguy",
            "fred gangster"
        }
    
    def _load_pep_list(self) -> set:
        """Load Politically Exposed Persons list (mock implementation)"""
        # In a real implementation, this would load from a database or API
        return {
            "political figure",
            "government official",
            "senior executive"
        }

# Usage example and helper functions
class KYCManager:
    def __init__(self):
        self.checker = KYCChecker()
        self.results_storage = {}  # In production, use a proper database
    
    def process_kyc_application(self, user_id: str, personal_info: PersonalInfo, 
                              documents: List[Document]) -> str:
        """Process a KYC application and return application ID"""
        result = self.checker.verify_user(personal_info, documents)
        
        application_id = self._generate_application_id(user_id)
        self.results_storage[application_id] = {
            'user_id': user_id,
            'personal_info': personal_info,
            'documents': documents,
            'result': result
        }
        
        return application_id
    
    def get_kyc_status(self, application_id: str) -> Optional[KYCResult]:
        """Get KYC status by application ID"""
        if application_id in self.results_storage:
            return self.results_storage[application_id]['result']
        return None
    
    def _generate_application_id(self, user_id: str) -> str:
        """Generate unique application ID"""
        timestamp = str(int(datetime.datetime.now().timestamp()))
        hash_input = f"{user_id}_{timestamp}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:12]

# Example usage
if __name__ == "__main__":
    # Create KYC manager
    kyc_manager = KYCManager()

    # Random user data
    # To randomise: first_name, last_name, date_of_birth, nationality, address, phone, email
    user_info = PersonalInfo(
        first_name="John",
        last_name="Doe",
        date_of_birth="01-01-1990",
        nationality="Singapore",
        address="Kent Ridge Avenue 1, Singapore",
        phone="+6512345678",
        email="john.doe@example.com"
    )
    
    # Sample documents
    NUM_DOCUMENTS = 3
    document_list = list(DocumentType)
    documents = []

    for i in range(NUM_DOCUMENTS):
        documents.append(
            Document(
                document_type=document_list[i],
                document_number=f"{random.choice(['S', 'T'])}{''.join(random.choices(string.digits, k=8))}{random.choice(string.ascii_uppercase)}",
                full_name=user_info.first_name + " " + user_info.last_name,
                issued_date=random.choice(["01-01-2017", "15-06-2021", "30-09-2023"]),
                expiry_date=random.choice(["01-01-2024", "15-06-2025", "30-09-2026"]),
                issuing_country="Singapore"
            )
        )

    print(10*"-"+"User Info"+10*"-")
    print(f" - Name: {user_info.first_name} {user_info.last_name}")
    print(f" - Date of Birth: {user_info.date_of_birth}")
    print(f" - Nationality: {user_info.nationality}")
    print(f" - Address: {user_info.address}")
    print(f" - Phone: {user_info.phone}")
    print(f" - Email: {user_info.email}")
    print(10*"-"+" Documents"+10*"-")
    for doc in documents:
        print(f" - {doc.document_type}")
        print(f"   Document Number: {doc.document_number}")
        print(f"   Full Name: {doc.full_name}")
        print(f"   Issued Date: {doc.issued_date}")
        print(f"   Expiry Date: {doc.expiry_date}")
        print(f"   Issuing Country: {doc.issuing_country}")

    # Process KYC application
    application_id = kyc_manager.process_kyc_application("user123", user_info, documents)
    
    # Get results
    result = kyc_manager.get_kyc_status(application_id)
    
    if result:
        print(f"KYC Status: {result.status.value}")
        print(f"KYC Level: {result.kyc_level.value}")
        print(f"Score: {result.score:.1f}/100")
        print(f"Flags: {result.flags}")