# Bot Account Detection: KYC and Phone Trust Score

A comprehensive fraud detection system that combines Know Your Customer (KYC) verification with phone number trust scoring to identify and prevent bot accounts, fraudulent registrations, and money laundering activities.

## 🏗️ Architecture Overview

This module provides two main components:
- **KYC Verification System** (`kyc.py`) - Document and personal data validation
- **Phone Trust Score System** (`trust_score.py`) - Phone number risk assessment inspired by Prove Trust Score

## 📁 Project Structure

```
bot_account_detection/
├── kyc.py                 # KYC verification and scoring
├── trust_score.py         # Phone trust score calculation
├── README.md             # This documentation
└── .env                  # Environment variables (ABSTRACT_API_KEY)
```

## 🔍 KYC Verification System (`kyc.py`)

### Features

The KYC system validates user identity through multiple verification layers:

#### Personal Information Validation
- **Name Format**: Validates names using regex patterns (letters, spaces, hyphens, apostrophes, periods)
- **Date of Birth**: Supports DD-MM-YYYY format, validates age range (0-120 years)
- **Phone Numbers**: E.164 format validation using `phonenumbers` library
- **Age Verification**: Ensures users are 18+ years old
- **Nationality Check**: Flags users from sanctioned/blacklisted countries

#### Document Verification
- **Supported Documents**: Passport, Driver's License, National ID
- **Expiry Validation**: Checks if documents are expired or outdated (>5 years)
- **Required Documents**: Ensures at least one valid ID document is provided
- **Cross-Reference**: Validates document names match personal information

#### Risk Assessment
- **Sanctions List**: Checks against mock sanctions database
- **PEP (Politically Exposed Person)**: Enhanced due diligence for political figures
- **Country Risk**: Assesses nationality-based risk factors

### Scoring System

| Score Range | KYC Level | Status | Description |
|-------------|-----------|---------|-------------|
| 80-100 | LOW_RISK | APPROVED | Standard processing |
| 60-79 | MEDIUM_RISK | REQUIRES_REVIEW | Additional verification needed |
| 30-59 | HIGH_RISK | REQUIRES_REVIEW | Enhanced due diligence |
| 0-29 | CRITICAL_RISK | REJECTED | Automatic rejection |

### Usage Example

```python
from kyc import KYCManager, PersonalInfo, Document, DocumentType

# Initialize KYC system
kyc_manager = KYCManager()

# Create user information
user_info = PersonalInfo(
    first_name="John",
    last_name="Doe", 
    date_of_birth="15-01-1990",  # DD-MM-YYYY
    nationality="Singapore",
    address="Kent Ridge Avenue 1, Singapore",
    phone="+6512345678",  # E.164 format
    email="john.doe@example.com"
)

# Create documents
documents = [
    Document(
        document_type=DocumentType.PASSPORT,
        document_number="S1234567A",
        full_name="John Doe",
        issued_date="01-01-2017",
        expiry_date="01-01-2027",
        issuing_country="Singapore"
    )
]

# Process KYC application
application_id = kyc_manager.process_kyc_application("user123", user_info, documents)

# Get results
result = kyc_manager.get_kyc_status(application_id)
print(f"Status: {result.status.value}")
print(f"Score: {result.score}/100")
print(f"Risk Level: {result.kyc_level.value}")
```

## 📱 Phone Trust Score System (`trust_score.py`)

### Features

The phone trust scoring system evaluates phone numbers across multiple dimensions:

#### Phone Type Risk Assessment
| Phone Type | Risk Score | Description |
|------------|------------|-------------|
| Unknown | 35 | Highest risk - unverifiable |
| Premium | 25 | High risk - expensive services, often fraud |
| Paging | 20 | High risk - outdated technology |
| Satellite | 15 | Medium-high risk - harder to trace |
| Toll_Free | 10 | Medium risk - can be spoofed |
| Mobile | 5 | Low risk - standard personal use |
| Landline | 5 | Low risk - traceable and established |
| Special | 0 | Lowest risk - emergency services |

#### Scoring Components

**Metadata Score (0-35 points)**
- Phone type validation
- Carrier information
- Country risk assessment
- Format validation

**Device Score (0-30 points)**
- Emulator detection (-30 points)
- Rooted/jailbroken device detection (-20 points)
- IP geolocation mismatch (-10 points)

**Activity Score (0-35 points)**
- Days since first seen
- Call/SMS activity patterns
- Recent communication history

### Trust Levels

| Score Range | Trust Level | Recommendation |
|-------------|-------------|----------------|
| 80-100 | VERY_HIGH | Proceed with high confidence |
| 60-79 | HIGH | Proceed with normal verification |
| 40-59 | MEDIUM | Proceed with additional verification |
| 20-39 | LOW | Verify with alternative method |
| 0-19 | VERY_LOW | Reject this phone number |

### Usage Example

```python
from trust_score import PhoneTrustScore
from datetime import datetime

# Initialize trust scorer
trust_scorer = PhoneTrustScore()

# Calculate trust score
result = trust_scorer.calculate_trust_score(
    phone_number="+6590123456",
    date=datetime.now().strftime("%d-%m-%Y")
)

print(f"Trust Score: {result.overall_score}/100")
print(f"Trust Level: {result.trust_level.value}")
print(f"Risk Factors: {result.risk_factors}")
```

## 🔧 Setup and Installation

### Prerequisites

```bash
pip install phonenumbers python-dotenv requests
```

### Environment Configuration

Create a `.env` file with your API keys:

```bash
ABSTRACT_API_KEY=your_abstract_api_key_here
```

### API Integration

The phone trust score system integrates with Abstract API for real-time phone validation:
- **API Endpoint**: `https://phonevalidation.abstractapi.com/v1/`
- **Fallback**: Simulation mode if API unavailable
- **Rate Limiting**: Caching implemented to reduce API calls

## 🛡️ Security Features

### Anti-Money Laundering (AML) Detection
- **Structuring Detection**: Multiple transactions below reporting thresholds
- **Velocity Checks**: Rapid movement of large funds
- **Smurfing Patterns**: Multiple small deposits to avoid detection
- **High-Risk Jurisdictions**: Transactions from sanctioned countries
- **Round Number Analysis**: Suspicious exact amounts

### Fraud Prevention
- **Device Fingerprinting**: Emulator and rooted device detection
- **Geolocation Validation**: IP location vs phone country matching
- **Behavioral Analysis**: Activity patterns inconsistent with profiles
- **Document Verification**: Expiry and authenticity checks

## 📊 Data Models

### Core Enums

```python
class KYCStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved" 
    REJECTED = "rejected"
    REQUIRES_REVIEW = "requires_review"

class TrustLevel(Enum):
    VERY_LOW = "very_low"     # 0-19: Likely fraudulent
    LOW = "low"               # 20-39: High risk
    MEDIUM = "medium"         # 40-59: Moderate risk  
    HIGH = "high"             # 60-79: Low risk
    VERY_HIGH = "very_high"   # 80-100: Very low risk
```

### Key Data Classes

- `PersonalInfo`: User personal information
- `Document`: Identity document details
- `KYCResult`: KYC verification outcome
- `PhoneMetadata`: Phone number metadata from API
- `TrustScoreResult`: Phone trust score outcome

## 🔄 Integration Patterns

### Combined Verification Flow

```python
def comprehensive_user_verification(user_data, documents, phone_number):
    # Step 1: KYC Verification
    kyc_result = kyc_manager.process_kyc_application(
        user_data['user_id'], 
        user_data['personal_info'], 
        documents
    )
    
    # Step 2: Phone Trust Scoring
    trust_result = trust_scorer.calculate_trust_score(
        phone_number, 
        datetime.now().strftime("%d-%m-%Y")
    )
    
    # Step 3: Combined Risk Assessment
    if kyc_result.status == KYCStatus.REJECTED or trust_result.trust_level == TrustLevel.VERY_LOW:
        return "REJECT"
    elif kyc_result.status == KYCStatus.REQUIRES_REVIEW or trust_result.trust_level in [TrustLevel.LOW, TrustLevel.MEDIUM]:
        return "MANUAL_REVIEW"
    else:
        return "APPROVE"
```

## 📈 Performance and Caching

- **Result Caching**: Implemented for phone trust scores to reduce API calls
- **Simulation Mode**: Fallback system for development and testing
- **Logging**: Comprehensive logging for audit trails and debugging
- **Response Times**: Typically <2 seconds for combined verification

## 🧪 Testing

The system includes built-in test scenarios that demonstrate various risk patterns:

```python
# Run examples
python kyc.py          # Test KYC verification
python trust_score.py  # Test phone trust scoring
```

## 🚀 Production Considerations

### Database Integration
- Replace in-memory storage with proper databases
- Implement proper indexing for performance
- Add audit logging for compliance

### API Rate Limiting
- Implement proper rate limiting for external APIs
- Add retry logic and circuit breakers
- Monitor API usage and costs

### Security Hardening
- Encrypt sensitive data at rest
- Implement proper access controls
- Add API authentication and authorization
- Regular security audits

### Compliance
- Ensure GDPR/CCPA compliance for data handling
- Implement data retention policies
- Add consent management
- Regular compliance audits

## 📝 License

This project is intended for educational and demonstration purposes. Ensure compliance with local regulations when implementing in production environments.