import streamlit as st
import sys
import os
from datetime import datetime, timedelta
from typing import List, Optional
import json

# Add the bot_account_detection directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../bot_account_detection'))

from bot_account_detection import KYCManager, PersonalInfo, DocumentInfo, KYCResult, KYCStatus, KYCLevel, DocumentType, PhoneTrustScore, TrustLevel

def initialize_session_state():
    """Initialize session state variables"""
    if 'kyc_result' not in st.session_state:
        st.session_state.kyc_result = None
    if 'trust_score_result' not in st.session_state:
        st.session_state.trust_score_result = None
    if 'form_submitted' not in st.session_state:
        st.session_state.form_submitted = False

def validate_form_data(personal_info: dict, documents: List[dict]) -> tuple[bool, List[str]]:
    """Validate form data and return validation status and error messages"""
    errors = []
    
    # Validate required personal information
    if not personal_info.get('first_name', '').strip():
        errors.append("First name is required")
    if not personal_info.get('last_name', '').strip():
        errors.append("Last name is required")
    if not personal_info.get('date_of_birth'):
        errors.append("Date of birth is required")
    if not personal_info.get('nationality', '').strip():
        errors.append("Nationality is required")
    if not personal_info.get('address', '').strip():
        errors.append("Address is required")
    if not personal_info.get('phone', '').strip():
        errors.append("Phone number is required")
    if not personal_info.get('email', '').strip():
        errors.append("Email is required")
    
    # Validate at least one document is provided
    if not documents or len(documents) == 0:
        errors.append("At least one identity document is required")
    else:
        for i, doc in enumerate(documents):
            if not doc.get('document_number', '').strip():
                errors.append(f"Document {i+1}: Document number is required")
            if not doc.get('full_name', '').strip():
                errors.append(f"Document {i+1}: Full name on document is required")
            if not doc.get('issued_date'):
                errors.append(f"Document {i+1}: Issued date is required")
            if not doc.get('issuing_country', '').strip():
                errors.append(f"Document {i+1}: Issuing country is required")
    
    return len(errors) == 0, errors

def format_date_for_backend(date_obj) -> str:
    """Convert date object to DD-MM-YYYY format required by backend"""
    if date_obj:
        return date_obj.strftime("%d-%m-%Y")
    return ""

def display_kyc_results(kyc_result: KYCResult, trust_score_result):
    """Display KYC and Trust Score results"""
    st.header("🔍 Verification Results")
    
    # Create columns for side-by-side display
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📋 KYC Verification")
        
        # Status display with color coding
        status_colors = {
            KYCStatus.APPROVED: "green",
            KYCStatus.PENDING: "orange", 
            KYCStatus.REJECTED: "red",
            KYCStatus.REQUIRES_REVIEW: "orange"
        }
        
        status_color = status_colors.get(kyc_result.status, "gray")
        st.markdown(f"**Status:** <span style='color: {status_color}'>{kyc_result.status.value.upper()}</span>", 
                   unsafe_allow_html=True)
        
        # Risk level display
        risk_colors = {
            KYCLevel.LOW_RISK: "green",
            KYCLevel.MEDIUM_RISK: "orange",
            KYCLevel.HIGH_RISK: "red", 
            KYCLevel.CRITICAL_RISK: "darkred"
        }
        
        risk_color = risk_colors.get(kyc_result.kyc_level, "gray")
        st.markdown(f"**Risk Level:** <span style='color: {risk_color}'>{kyc_result.kyc_level.name}</span>", 
                   unsafe_allow_html=True)
        
        # Score with progress bar
        st.metric("KYC Score", f"{kyc_result.score}/100")
        st.progress(kyc_result.score / 100)
        
        # Flags
        if kyc_result.flags:
            st.write("**⚠️ Issues Identified:**")
            for flag in kyc_result.flags:
                st.write(f"• {flag}")
        else:
            st.write("✅ No issues identified")
    
    with col2:
        st.subheader("📱 Phone Trust Score")
        
        if trust_score_result:
            # Trust level display
            trust_colors = {
                TrustLevel.VERY_HIGH: "green",
                TrustLevel.HIGH: "lightgreen",
                TrustLevel.MEDIUM: "orange",
                TrustLevel.LOW: "red",
                TrustLevel.VERY_LOW: "darkred"
            }
            
            trust_color = trust_colors.get(trust_score_result.trust_level, "gray")
            st.markdown(f"**Trust Level:** <span style='color: {trust_color}'>{trust_score_result.trust_level.value.upper()}</span>", 
                       unsafe_allow_html=True)
            
            # Score with progress bar
            st.metric("Trust Score", f"{trust_score_result.overall_score}/100")
            st.progress(trust_score_result.overall_score / 100)
            
            # Sub-scores breakdown
            st.write("**📊 Score Breakdown:**")
            for category, score in trust_score_result.sub_scores.items():
                st.write(f"• {category.title()}: {score}")
            
            # Risk factors
            if trust_score_result.risk_factors:
                st.write("**⚠️ Risk Factors:**")
                for factor in trust_score_result.risk_factors:
                    st.write(f"• {factor}")
            else:
                st.write("✅ No risk factors identified")
        else:
            st.write("❌ Trust score calculation failed")
    
    # Overall recommendation
    st.subheader("🎯 Recommendation")
    
    # Determine overall recommendation based on both scores
    if (kyc_result.status == KYCStatus.APPROVED and 
        trust_score_result and trust_score_result.trust_level in [TrustLevel.HIGH, TrustLevel.VERY_HIGH]):
        st.success("✅ **APPROVED** - User meets all verification requirements")
    elif (kyc_result.status == KYCStatus.REJECTED or 
          (trust_score_result and trust_score_result.trust_level == TrustLevel.VERY_LOW)):
        st.error("❌ **REJECTED** - User does not meet verification requirements")
    else:
        st.warning("🔍 **REQUIRES MANUAL REVIEW** - Additional verification needed")
    
    # Verification timestamp
    st.caption(f"Verification completed on: {kyc_result.verification_date}")

def main():
    st.set_page_config(
        page_title="KYC Verification",
        page_icon="🔍",
        layout="wide"
    )
    
    initialize_session_state()
    
    st.title("🔍 Know Your Customer (KYC) Verification")
    st.write("Please complete the form below to verify your identity and assess your account trustworthiness.")
    
    # Create tabs for form and results
    if not st.session_state.form_submitted:
        tab1, tab2 = st.tabs(["📝 Personal Information", "📄 Identity Documents"])
        
        with tab1:
            st.header("📝 Personal Information")
            
            # Personal information form
            col1, col2 = st.columns(2)
            
            with col1:
                first_name = st.text_input("First Name *", placeholder="Enter your first name")
                last_name = st.text_input("Last Name *", placeholder="Enter your last name")
                date_of_birth = st.date_input(
                    "Date of Birth *", 
                    min_value=datetime.now() - timedelta(days=365*120),  # 120 years ago
                    max_value=datetime.now() - timedelta(days=365*18),   # 18 years ago
                    value=None
                )
                nationality = st.selectbox(
                    "Nationality *",
                    ["", "Singapore", "Malaysia", "United States", "United Kingdom", "Australia", "Canada", "Other"],
                    index=0
                )
            
            with col2:
                address = st.text_area("Address *", placeholder="Enter your full address")
                phone = st.text_input("Phone Number *", placeholder="+65XXXXXXXX")
                email = st.text_input("Email Address *", placeholder="your.email@example.com")
        
        with tab2:
            st.header("📄 Identity Documents")
            st.write("Please provide at least one valid identity document.")
            
            # Document input
            documents = []
            
            # Allow up to 3 documents
            for i in range(3):
                st.subheader(f"Document {i+1}" + (" (Required)" if i == 0 else " (Optional)"))
                
                col1, col2 = st.columns(2)
                
                with col1:
                    doc_type = st.selectbox(
                        "Document Type",
                        ["", "passport", "drivers_license", "national_id"],
                        key=f"doc_type_{i}",
                        format_func=lambda x: {
                            "": "Select document type",
                            "passport": "Passport",
                            "drivers_license": "Driver's License", 
                            "national_id": "National ID"
                        }.get(x, x)
                    )
                    
                    doc_number = st.text_input(
                        "Document Number",
                        key=f"doc_number_{i}",
                        placeholder="Enter document number"
                    )
                    
                    full_name_on_doc = st.text_input(
                        "Full Name on Document",
                        key=f"doc_name_{i}",
                        placeholder="Name as shown on document"
                    )
                
                with col2:
                    issued_date = st.date_input(
                        "Issued Date",
                        key=f"issued_date_{i}",
                        min_value=datetime.now() - timedelta(days=365*20),
                        max_value=datetime.now(),
                        value=None
                    )
                    
                    expiry_date = st.date_input(
                        "Expiry Date (if applicable)",
                        key=f"expiry_date_{i}",
                        min_value=datetime.now(),
                        max_value=datetime.now() + timedelta(days=365*20),
                        value=None
                    )
                    
                    issuing_country = st.text_input(
                        "Issuing Country",
                        key=f"issuing_country_{i}",
                        placeholder="Country that issued this document"
                    )
                
                # Only add document if type is selected
                if doc_type:
                    documents.append({
                        'document_type': doc_type,
                        'document_number': doc_number,
                        'full_name': full_name_on_doc,
                        'issued_date': issued_date,
                        'expiry_date': expiry_date,
                        'issuing_country': issuing_country
                    })
                
                st.divider()
        
        # Submit button
        if st.button("🔍 Submit for Verification", type="primary", use_container_width=True):
            # Collect personal information
            personal_info = {
                'first_name': first_name,
                'last_name': last_name,
                'date_of_birth': date_of_birth,
                'nationality': nationality,
                'address': address,
                'phone': phone,
                'email': email
            }
            
            # Validate form data
            is_valid, errors = validate_form_data(personal_info, documents)
            
            if not is_valid:
                st.error("Please fix the following errors:")
                for error in errors:
                    st.write(f"• {error}")
            else:
                # Process the verification
                with st.spinner("Processing verification... This may take a moment."):
                    try:
                        # Create PersonalInfo object
                        personal_info_obj = PersonalInfo(
                            first_name=first_name,
                            last_name=last_name,
                            date_of_birth=format_date_for_backend(date_of_birth),
                            nationality=nationality,
                            address=address,
                            phone=phone,
                            email=email
                        )
                        
                        # Create Document objects
                        document_objects = []
                        for doc in documents:
                            if doc['document_type']:  # Only process if document type is selected
                                document_objects.append(DocumentInfo(
                                    document_type=DocumentType(doc['document_type']),
                                    document_number=doc['document_number'],
                                    full_name=doc['full_name'],
                                    issued_date=format_date_for_backend(doc['issued_date']),
                                    expiry_date=format_date_for_backend(doc['expiry_date']) if doc['expiry_date'] else "",
                                    issuing_country=doc['issuing_country']
                                ))
                        
                        # Initialize KYC checker
                        kyc_manager = KYCManager()
                        
                        # Process KYC verification
                        application_id = kyc_manager.process_kyc_application(
                            user_id="demo_user",
                            personal_info=personal_info_obj,
                            documents=document_objects
                        )
                        
                        kyc_result = kyc_manager.get_kyc_status(application_id)
                        
                        # Calculate trust score for phone number
                        trust_scorer = PhoneTrustScore()
                        trust_score_result = trust_scorer.calculate_trust_score(
                            phone_number=phone,
                            date=datetime.now().strftime("%d-%m-%Y")
                        )
                        
                        # Store results in session state
                        st.session_state.kyc_result = kyc_result
                        st.session_state.trust_score_result = trust_score_result
                        st.session_state.form_submitted = True
                        
                        st.success("✅ Verification completed! Scroll down to see results.")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ An error occurred during verification: {str(e)}")
                        st.error("Please check your input and try again.")
    
    # Display results if available
    if st.session_state.form_submitted and st.session_state.kyc_result:
        display_kyc_results(st.session_state.kyc_result, st.session_state.trust_score_result)
        
        # Reset button
        if st.button("🔄 Start New Verification", type="secondary"):
            st.session_state.form_submitted = False
            st.session_state.kyc_result = None
            st.session_state.trust_score_result = None
            st.rerun()

if __name__ == "__main__":
    main()