"""Dataset label -> canonical EntityType.

`None` means the label is excluded from evaluation, with the reason recorded in EXCLUDED.
Excluding a label is a methodological decision, so every exclusion is written down here
and repeated in the evaluation report.
"""

from __future__ import annotations

from privacy_review.schemas.entities import EntityType as E

AI4PRIVACY: dict[str, E | None] = {
    "FIRSTNAME": E.PERSON, "MIDDLENAME": E.PERSON, "LASTNAME": E.PERSON,
    "EMAIL": E.EMAIL_ADDRESS, "PHONENUMBER": E.PHONE_NUMBER,
    "STREET": E.STREET_ADDRESS, "BUILDINGNUMBER": E.STREET_ADDRESS, "SECONDARYADDRESS": E.STREET_ADDRESS,
    "CITY": E.LOCATION, "STATE": E.LOCATION, "COUNTY": E.LOCATION,
    "ZIPCODE": E.POSTAL_CODE, "NEARBYGPSCOORDINATE": E.GPS_COORDINATE,
    "DATE": E.DATE, "DOB": E.DATE_OF_BIRTH, "AGE": E.AGE,
    "SSN": E.GOVERNMENT_ID,
    "ACCOUNTNUMBER": E.FINANCIAL_ACCOUNT, "IBAN": E.FINANCIAL_ACCOUNT, "CREDITCARDNUMBER": E.FINANCIAL_ACCOUNT,
    "CREDITCARDCVV": E.FINANCIAL_ACCOUNT, "MASKEDNUMBER": E.FINANCIAL_ACCOUNT,
    "BIC": E.FINANCIAL_ACCOUNT, "BITCOINADDRESS": E.FINANCIAL_ACCOUNT, "ETHEREUMADDRESS": E.FINANCIAL_ACCOUNT, "LITECOINADDRESS": E.FINANCIAL_ACCOUNT,
    "PASSWORD": E.CREDENTIAL, "PIN": E.CREDENTIAL,
    "USERNAME": E.ONLINE_IDENTIFIER, "IP": E.ONLINE_IDENTIFIER, "IPV4": E.ONLINE_IDENTIFIER,
    "IPV6": E.ONLINE_IDENTIFIER, "MAC": E.ONLINE_IDENTIFIER, "USERAGENT": E.ONLINE_IDENTIFIER,
    "URL": E.URL,
    "PHONEIMEI": E.DEVICE_IDENTIFIER, "VEHICLEVIN": E.DEVICE_IDENTIFIER, "VEHICLEVRM": E.DEVICE_IDENTIFIER,
    "COMPANYNAME": E.ORGANIZATION,
    "JOBTITLE": E.OCCUPATION, "JOBAREA": E.OCCUPATION, "JOBTYPE": E.OCCUPATION,
    "GENDER": E.DEMOGRAPHIC, "SEX": E.DEMOGRAPHIC, "EYECOLOR": E.DEMOGRAPHIC, "HEIGHT": E.DEMOGRAPHIC,
    # excluded
    "AMOUNT": None, "CURRENCY": None, "CURRENCYCODE": None, "CURRENCYNAME": None, "CURRENCYSYMBOL": None,
    "CREDITCARDISSUER": None, "ACCOUNTNAME": None, "ORDINALDIRECTION": None, "PREFIX": None, "TIME": None,
}

PIIMB_SNAKE: dict[str, E | None] = {      # gretel + nemotron-pii
    "name": E.PERSON, "first_name": E.PERSON, "last_name": E.PERSON,
    "email": E.EMAIL_ADDRESS, "phone_number": E.PHONE_NUMBER, "fax_number": E.PHONE_NUMBER,
    "street_address": E.STREET_ADDRESS, "address": E.STREET_ADDRESS,
    "city": E.LOCATION, "state": E.LOCATION, "county": E.LOCATION, "country": E.LOCATION,
    "postcode": E.POSTAL_CODE, "coordinate": E.GPS_COORDINATE,
    "date": E.DATE, "date_time": E.DATE, "date_of_birth": E.DATE_OF_BIRTH, "age": E.AGE,
    "ssn": E.GOVERNMENT_ID, "national_id": E.GOVERNMENT_ID, "tax_id": E.GOVERNMENT_ID,
    "certificate_license_number": E.GOVERNMENT_ID,
    "medical_record_number": E.RECORD_IDENTIFIER, "customer_id": E.RECORD_IDENTIFIER,
    "employee_id": E.RECORD_IDENTIFIER, "health_plan_beneficiary_number": E.RECORD_IDENTIFIER,
    "unique_identifier": E.RECORD_IDENTIFIER, "unique_id": E.RECORD_IDENTIFIER,
    "biometric_identifier": E.RECORD_IDENTIFIER,
    "account_number": E.FINANCIAL_ACCOUNT, "credit_card_number": E.FINANCIAL_ACCOUNT,
    "credit_debit_card": E.FINANCIAL_ACCOUNT, "bank_routing_number": E.FINANCIAL_ACCOUNT,
    "swift_bic": E.FINANCIAL_ACCOUNT, "cvv": E.FINANCIAL_ACCOUNT,
    "password": E.CREDENTIAL, "pin": E.CREDENTIAL, "api_key": E.CREDENTIAL, "http_cookie": E.CREDENTIAL,
    "user_name": E.ONLINE_IDENTIFIER, "ipv4": E.ONLINE_IDENTIFIER, "ipv6": E.ONLINE_IDENTIFIER,
    "mac_address": E.ONLINE_IDENTIFIER, "url": E.URL,
    "device_identifier": E.DEVICE_IDENTIFIER, "license_plate": E.DEVICE_IDENTIFIER,
    "vehicle_identifier": E.DEVICE_IDENTIFIER,
    "company_name": E.ORGANIZATION, "occupation": E.OCCUPATION, "employment_status": E.OCCUPATION,
    "gender": E.DEMOGRAPHIC, "race_ethnicity": E.DEMOGRAPHIC, "religious_belief": E.DEMOGRAPHIC,
    "political_view": E.DEMOGRAPHIC, "sexuality": E.DEMOGRAPHIC, "education_level": E.DEMOGRAPHIC,
    "language": E.DEMOGRAPHIC, "blood_type": E.MEDICAL_CONDITION,
    "time": None,
}

PIIMB_PRESIDIO_STYLE: dict[str, E | None] = {   # privy
    "PERSON": E.PERSON, "LOCATION": E.LOCATION, "NRP": E.DEMOGRAPHIC, "DATE_TIME": E.DATE,
    "COORDINATE": E.GPS_COORDINATE, "ORGANIZATION": E.ORGANIZATION, "EMAIL_ADDRESS": E.EMAIL_ADDRESS,
    "PHONE_NUMBER": E.PHONE_NUMBER, "URL": E.URL, "FINANCIAL": E.FINANCIAL_ACCOUNT, "AGE": E.AGE,
    "IP_ADDRESS": E.ONLINE_IDENTIFIER, "PASSWORD": E.CREDENTIAL, "US_ITIN": E.GOVERNMENT_ID,
    "US_LICENSE_PLATE": E.DEVICE_IDENTIFIER, "US_SSN": E.GOVERNMENT_ID, "US_PASSPORT": E.GOVERNMENT_ID,
    "CREDIT_CARD": E.FINANCIAL_ACCOUNT, "IMEI": E.DEVICE_IDENTIFIER, "MAC_ADDRESS": E.ONLINE_IDENTIFIER,
    "US_DRIVER_LICENSE": E.GOVERNMENT_ID, "US_BANK_NUMBER": E.FINANCIAL_ACCOUNT, "IBAN_CODE": E.FINANCIAL_ACCOUNT,
    "TITLE": None,
}

EXCLUDED: dict[str, str] = {
    "AMOUNT / CURRENCY*": "monetary amounts and currency names do not identify a person",
    "CREDITCARDISSUER": "card network names (Visa, Mastercard) are shared by millions",
    "ACCOUNTNAME": "in ai4privacy this is an account product name (e.g. 'Savings Account'), not an identifier",
    "ORDINALDIRECTION": "compass directions are not personal data",
    "PREFIX / TITLE": "honorifics (Mr., Dr.) do not identify on their own",
    "TIME / time": "a time of day alone is not identifying; date_time is kept",
}

# Labels whose adjacent spans describe one mention (first + last name; number + street).
MERGE_ADJACENT = {E.PERSON, E.STREET_ADDRESS}


def map_label(label: str, scheme: str) -> E | None:
    table = {"ai4privacy": AI4PRIVACY, "piimb_snake": PIIMB_SNAKE, "piimb_presidio": PIIMB_PRESIDIO_STYLE}[scheme]
    if label not in table:
        raise KeyError(f"unmapped {scheme} label '{label}' - add it to label_maps.py")
    return table[label]
