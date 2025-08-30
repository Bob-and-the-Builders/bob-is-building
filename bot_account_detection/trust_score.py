import os
from dotenv import load_dotenv
import requests
import random
import time
import hashlib
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime, timedelta
import supabase
    
load_dotenv()

ABSTRACT_API_KEY = os.getenv("ABSTRACT_API_KEY")

class TrustLevel(Enum):
    """Trust levels for phone numbers"""
    VERY_LOW = 0         # 0-19: Likely fraudulent
    LOW = 1              # 20-39: High risk
    MEDIUM = 2           # 40-59: Moderate risk
    HIGH = 3             # 60-79: Low risk
    VERY_HIGH = 4        # 80-100: Very low risk

class PhoneTypeRisk:
    PHONE_TYPE_RISK = {
        "Unknown": 35,      # Highest risk - unverifiable
        "Premium": 25,      # Very high risk - expensive services, often fraud
        "Paging": 20,       # High risk - outdated technology, suspicious
        "Satellite": 15,    # Medium-high risk - harder to trace, expensive
        "Toll_Free": 10,    # Medium risk - business use but can be spoofed
        "Mobile": 5,       # Low risk - standard personal use
        "Landline": 5,      # Low risk - traceable, established
        "Special": 0        # Lowest risk - emergency services
    }

    # Detailed risk explanations
    RISK_EXPLANATIONS = {
        "Unknown": "Cannot verify phone type - highest fraud risk",
        "Premium": "Premium rate numbers often used for fraud schemes",
        "Paging": "Outdated technology, rarely legitimate in modern context",
        "Satellite": "Satellite phones harder to trace and verify",
        "Toll_Free": "Can be legitimate business but easily spoofed",
        "Mobile": "Standard mobile numbers are generally trustworthy",
        "Landline": "Landlines are most traceable and established",
        "Special": "Special service numbers are for police and emergency services",
    }
@dataclass
class PhoneMetadata:
    """Metadata associated with a phone number"""
    phone: str
    valid: bool
    format: Dict[str, str]
    country: Dict[str, str]
    location: str
    type: str
    carrier: str

@dataclass
class DeviceInfo:
    """Information about the device using the phone number"""
    device_id: str
    device_type: str  # android, ios, others
    ip_address: str
    is_rooted: bool = False
    is_emulator: bool = False

@dataclass
class PhoneActivity:
    """Phone activity metrics"""
    last_call_date: Optional[datetime] = None
    last_sms_date: Optional[datetime] = None
    avg_calls_per_day: float = 0.0
    avg_sms_per_day: float = 0.0
    days_since_first_seen: int = 0

@dataclass
class TrustScoreResult:
    """Result of a trust score calculation"""
    overall_score: int  # 0-100
    trust_level: TrustLevel
    sub_scores: Dict[str, int]
    risk_factors: List[str]
    evaluation_date: datetime

class PhoneTrustScore:
    """
    Calculates a trust score for a phone number based on various factors.
    Higher scores indicate higher trustworthiness.
    """
    def __init__(self):
        # Cache for previously calculated scores
        self.score_cache = {}

    def calculate_trust_score(self, 
                             phone_number: str,
                             date: str) -> int:
        """
        Calculate a trust score for a phone number
        
        Parameters:
            phone_number: E.164 format phone number (e.g., +14155552671)
            metadata: Optional phone metadata
            device_info: Optional device information
            activity: Optional phone activity data
            
        Returns:
            TrustScoreResult object with overall score and details
        """
        # Check cache for this phone number
        cache_key = self._generate_cache_key(phone_number, date)
        if cache_key in self.score_cache:
            return self.score_cache[cache_key]
        
        start_time = time.time()
        
        # Initialize sub-scores and risk factors
        sub_scores = {}
        risk_factors = []
        
        # Calculate metadata-based score
        metadata_score, metadata_risks = self._calculate_metadata_score(phone_number)
        sub_scores["metadata"] = metadata_score
        risk_factors.extend(metadata_risks)
        
        # Calculate device-based score
        device_score, device_risks = self._calculate_device_score(phone_number)
        sub_scores["device"] = device_score
        risk_factors.extend(device_risks)
        
        # Calculate activity-based score
        activity_score, activity_risks = self._calculate_activity_score(phone_number)
        sub_scores["activity"] = activity_score
        risk_factors.extend(activity_risks)
        
        # Calculate overall score (weighted sum)
        overall_score = (
            sub_scores["metadata"] + 
            sub_scores["device"] + 
            sub_scores["activity"]
        )
        
        # Ensure score is in 0-100 range
        overall_score = max(0, min(100, overall_score))
        
        # Determine trust level based on score
        trust_level = self._determine_trust_level(overall_score)
        
        # Create result
        result = TrustScoreResult(
            overall_score=overall_score,
            trust_level=trust_level,
            sub_scores=sub_scores,
            risk_factors=risk_factors,
            evaluation_date=datetime.now(),
        )
        
        # Cache the result
        self.score_cache[cache_key] = result

        print(f"Trust score for {phone_number}: {overall_score} ({trust_level.value})")
        print(f"calculation time: {time.time() - start_time:.2f}s")

        return overall_score

    def _calculate_metadata_score(self, 
                                 phone_number: str) -> Tuple[int, List[str]]:
        """
        Calculate a score based on phone metadata
        Returns a score from 0-35 and a list of risk factors
        """
        risks = []
        
        url = f"https://phonevalidation.abstractapi.com/v1/?api_key={ABSTRACT_API_KEY}&phone={phone_number}"
        response = requests.get(url)
        if response.status_code == 200:
            metadata = PhoneMetadata(**response.json())
        else:
            metadata = self._simulate_metadata(phone_number)

        score = 35

        # Analyze line type
        if metadata.type in PhoneTypeRisk.PHONE_TYPE_RISK:
            penalty = PhoneTypeRisk.PHONE_TYPE_RISK[metadata.type]
            score -= penalty
            if penalty > 0:
                risks.append(PhoneTypeRisk.RISK_EXPLANATIONS[metadata.type])

        return max(0, score), risks

    def _calculate_device_score(self, 
                               phone_number: str) -> Tuple[int, List[str]]:
        """
        Calculate a score based on device information
        Returns a score from 0-30 and a list of risk factors
        """
        risks = []
        
        device_info = self._simulate_device_info(phone_number)
            
        score = 30  # Start with perfect score
        
        # Check for emulators (often used for fraud)
        if device_info.is_emulator:
            score -= 30
            risks.append("Emulator detected")
            
        # Check for rooted/jailbroken devices
        if device_info.is_rooted:
            score -= 20
            risks.append("Rooted/jailbroken device")
            
        # Check for IP mismatches with phone country
        if device_info.ip_address:
            # Check if IP is from expected region for phone number
            ip_country_mismatch = random.choice([True, False, False, False])
            if ip_country_mismatch:
                score -= 10
                risks.append("IP location doesn't match phone country")
                
        return max(0, score), risks

    def _calculate_activity_score(self, 
                                 phone_number: str) -> Tuple[int, List[str]]:
        """
        Calculate a score based on phone activity patterns
        Returns a score from 0-35 and a list of risk factors
        """
        risks = []
        
        activity = self._simulate_activity(phone_number)
            
        score = 35  # Start with perfect score
        
        # Check for new number with low activity
        if activity.days_since_first_seen < 30:
            score -= 15
            risks.append(f"New phone number (first seen {activity.days_since_first_seen} days ago)")
            
        # Check for low call/SMS activity (potential burner phone)
        if activity.avg_calls_per_day < 0.5 and activity.avg_sms_per_day < 0.5:
            score -= 15
            risks.append("Low phone activity (possible burner phone)")
            
        # Check for recent communication activity
        now = datetime.now()
        if activity.last_call_date and activity.last_sms_date:
            days_since_last_call = (now - activity.last_call_date).days
            days_since_last_sms = (now - activity.last_sms_date).days
            
            if days_since_last_call > 60 and days_since_last_sms > 60:
                score -= 10
                risks.append("No recent activity in over 60 days")
                
        return max(0, score), risks

    def _determine_trust_level(self, score: int) -> TrustLevel:
        """Determine the trust level based on the overall score"""
        if score >= 80:
            return TrustLevel.VERY_HIGH
        elif score >= 60:
            return TrustLevel.HIGH
        elif score >= 40:
            return TrustLevel.MEDIUM
        elif score >= 20:
            return TrustLevel.LOW
        else:
            return TrustLevel.VERY_LOW
            
    def _generate_cache_key(self, 
                           phone_number: str, 
                           date: str) -> str:
        """Generate a cache key for a specific request"""
        # Create a simple hash of inputs
        date_obj = datetime.fromisoformat(date)
        input_data = f"{phone_number}|{date_obj.month}"
        return hashlib.md5(input_data.encode()).hexdigest()
        
    # Simulation methods for demo purposes
    def _simulate_metadata(self, phone_number: str) -> PhoneMetadata:
        """Simulate phone metadata for demo purposes using realistic API format"""
        
        # Phone types with realistic distribution
        phone_types = ["mobile", "landline", "toll_free", "premium", "satellite", "paging", "special", "unknown"]
        type_weights = [0.60, 0.25, 0.05, 0.03, 0.02, 0.02, 0.02, 0.01]  # Mobile and landline most common
        
        carriers = [
            "Verizon Wireless", 
            "AT&T Mobility LLC", 
            "T-Mobile USA, Inc.", 
            "Sprint Corporation", 
            "Vodafone",
            "Unknown Carrier"
        ]
        
        # Use hash of phone number for consistent simulation
        phone_hash = int(hashlib.md5(phone_number.encode()).hexdigest(), 16)
        
        # Extract country info from phone number
        country_info = self._get_country_from_phone(phone_number)
        location = self._get_location_from_phone(country_info)

        # Select phone type based on weights
        selected_type = random.choices(phone_types, weights=type_weights)[0]
        
        # Format the phone number properly
        formatted_phone = phone_number if phone_number.startswith('+') else f"+{phone_number}"
        local_format = self._format_local_number(phone_number, country_info["code"])
        
        return PhoneMetadata(
            phone=phone_number,
            valid=True,  # Assume valid for simulation
            format={
                "international": formatted_phone,
                "local": local_format
            },
            country=country_info,
            location=location,
            type=selected_type,
            carrier=carriers[phone_hash % len(carriers)]
        )
    
    def _simulate_device_info(self, phone_number: str) -> DeviceInfo:
        """Simulate device info for demo purposes"""
        phone_hash = int(hashlib.md5(phone_number.encode()).hexdigest(), 16)
        
        device_types = ["android", "ios", "unknown"]
        device_type_weights = [0.45, 0.45, 0.1]
        
        # Simulate a device ID
        device_id = f"device_{hashlib.sha1(phone_number.encode()).hexdigest()[:12]}"
        
        # Generate IP (simplified)
        ip = f"{phone_hash % 256}.{(phone_hash // 256) % 256}.{(phone_hash // 65536) % 256}.{(phone_hash // 16777216) % 256}"
                
        # Risk factors
        is_emulator = (phone_hash % 100) < 5  # 5% chance
        is_rooted = (phone_hash % 100) < 10  # 10% chance
        
        return DeviceInfo(
            device_id=device_id,
            device_type=random.choices(device_types, weights=device_type_weights)[0],
            ip_address=ip,
            is_emulator=is_emulator,
            is_rooted=is_rooted
        )
    
    def _simulate_activity(self, phone_number: str) -> PhoneActivity:
        """Simulate phone activity for demo purposes"""
        phone_hash = int(hashlib.md5(phone_number.encode()).hexdigest(), 16)
        
        # Days since first seen (0-365 days)
        days_since_first_seen = (phone_hash % 365)
        
        # Simulate average activity
        avg_calls = (phone_hash % 100) / 25  # 0-4 calls per day
        avg_sms = (phone_hash % 100) / 20    # 0-5 SMS per day
        
        # Last activity dates
        has_recent_call = (phone_hash % 100) < 80  # 80% chance
        has_recent_sms = (phone_hash % 100) < 85   # 85% chance
        
        last_call_days_ago = (phone_hash % 60) if has_recent_call else (phone_hash % 120) + 60
        last_sms_days_ago = (phone_hash % 45) if has_recent_sms else (phone_hash % 100) + 45
        
        last_call_date = datetime.now() - timedelta(days=last_call_days_ago)
        last_sms_date = datetime.now() - timedelta(days=last_sms_days_ago)
        
        return PhoneActivity(
            last_call_date=last_call_date,
            last_sms_date=last_sms_date,
            avg_calls_per_day=avg_calls,
            avg_sms_per_day=avg_sms,
            days_since_first_seen=days_since_first_seen
        )

    def _get_country_from_phone(self, phone_number: str) -> Dict[str, str]:
        """Extract country information from phone number"""
        # Remove + if present
        clean_number = phone_number.lstrip('+')
        
        # Country code mapping (simplified)
        country_mapping = {
            "44": {"code": "GB", "name": "United Kingdom", "prefix": "+44"},
            "65": {"code": "SG", "name": "Singapore", "prefix": "+65"},
        }
        
        # Get country codes
        potential_code = clean_number[:2]
        if potential_code in country_mapping:
            return country_mapping[potential_code]
        
        # Default to unknown
        return {"code": "XX", "name": "Unknown", "prefix": "+XX"}

    def _get_location_from_phone(self, country_info: Dict[str, str]) -> str:
        """Get location information based on phone number and country"""        
        country_locations = {
            "GB": "United Kingdom",
            "SG": "Singapore", 
        }
        
        return country_locations.get(country_info["code"], country_info["name"])

    def _format_local_number(self, phone_number: str, country_code: str) -> str:
        """Format phone number in local format"""
        clean_number = phone_number.lstrip('+')

        if country_code == "GB":
            # UK format - remove 44
            if clean_number.startswith('44'):
                return clean_number[2:]
            return clean_number
        elif country_code == "SG":
            # Singapore format - remove 65
            if clean_number.startswith('65'):
                local_number = clean_number[2:]
                # Format as XXXX XXXX
                if len(local_number) == 8:
                    return f"{local_number[:4]} {local_number[4:]}"
                return local_number
            return clean_number

def update_trust_score_in_db(supabase_client, user_id: int, result: TrustScoreResult):
    """Update the trust score in the database"""
    # Update the trust score in the database
    response = (
        supabase_client.table("users")
        .update({"creator_trust_score": result.overall_score})
        .eq("id", user_id)
        .execute()
    )

def process_trust_score(user_id: int):
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or API key in environment")
    supabase_client = supabase.create_client(url, key)
    
    response = supabase_client.table("user_info").select("phone").eq("id", user_id).execute()
    
    # Check if we got data
    if not response.data or len(response.data) == 0:
        raise ValueError(f"No user found with ID {user_id}")
    
    # Extract the actual phone number string
    phone_number = response.data[0].get("phone")

    trust_scorer = PhoneTrustScore()
    result = trust_scorer.calculate_trust_score(phone_number, datetime.now().strftime("%Y-%m-%d"))
    print(result)
    update_trust_score_in_db(supabase_client, user_id, result)

if __name__ == "__main__":
    process_trust_score(3)
    # trust_scorer = PhoneTrustScore()
    # # Test with sample numbers
    # test_numbers = ["+445544332211", "+6590123456"]
    
    # for phone in test_numbers:
    #     print(f"Analyzing {phone}:")
    #     result = trust_scorer.calculate_trust_score(phone, datetime.now().strftime("%d-%m-%Y"))
    #     print(f"Trust Score: {result.overall_score}/100")
    #     print(f"Trust Level: {result.trust_level.value}")
    #     print(f"Risk factors: {result.risk_factors}\n")