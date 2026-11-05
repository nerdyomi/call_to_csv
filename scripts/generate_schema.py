"""Bootstrap config/schema.yaml from the CEX header.

The generated YAML is the source of truth afterwards: edit it by hand as the
form's allowed values get finalised. Re-running this script overwrites it, so
only use it to start over.

    python scripts/generate_schema.py "reference/CEX data/CEX.csv" config/schema.yaml
"""
import csv
import sys
from pathlib import Path

import yaml

CROPS = ["maize", "potato", "paddy", "onion", "chili", "mustard"]
LIVESTOCK = ["cow", "goat", "duck", "poultry", "fisheries"]

INCOME_SOURCES = ["agriculture", "business", "labor", "govt_job", "private_job", "driving", "stipend", "others"]

# name -> (type, description, known_values)
# type: text | number | enum | multi. `known_values` are values seen so far, not a closed list,
# unless the field also appears in ALLOWED_CLOSED.
SPECS: dict[str, tuple] = {
    "Notes": ("text", "Short summary of the call in romanized Bangla (Banglish), same style as the CEX agents write by hand.", None),
    "current_landsize": ("number", "Total land the farmer cultivates this season, in decimals (shotok).", None),
    "previous_year_landsize": ("number", "Total land the farmer cultivated last year, in decimals (shotok).", None),
    "invest": ("number", "Total cost the farmer invests in the loan's main crop/project, BDT.", None),
    "yield": ("number", "Total production of the loan's main crop/project, in kg. If the farmer speaks in maund (mon), convert at 1 maund = 40 kg.", None),
    "unit_price": ("number", "Selling price per maund of the loan's main crop, BDT.", None),
    "loan_amount": ("number", "Loan amount the farmer wants to take, BDT.", None),
    "farmland": ("multi", "Land-holding types the farmer has.", ["own", "lease_mortgage"]),
    "own": ("number", "Land the farmer personally owns, in decimals.", None),
    "lease_mortgage": ("number", "Land taken on lease or mortgage, in decimals.", None),
    "household_farm_assets": ("multi", "Livestock/poultry kept at home.", ["cow", "goat", "sheep", "duck", "chicken", "horse", "other"]),
    "number_of_cows": ("number", "Number of cows owned.", None),
    "number_of_goats": ("number", "Number of goats owned.", None),
    "number_of_sheep": ("number", "Number of sheep owned.", None),
    "number_of_ducks": ("number", "Number of ducks owned.", None),
    "number_of_chicken": ("number", "Number of chickens owned.", None),
    "number_of_horses": ("number", "Number of horses owned.", None),
    "other_farm_asset_names": ("text", "Names of other farm animals/assets not listed above.", None),
    "number_of_other_farm_assets": ("number", "Count of those other farm assets.", None),
    "farmer_assets": ("multi", "Household assets owned.", ["tv", "fridge", "motor_pump", "cycle", "smartphone", "buttonphone"]),
    "smart_phone_ownership": ("enum", "Who owns the smartphone.", ["self", "family"]),
    "agri_machineries": ("multi", "Farm machinery the farmer owns or has access to.", ["shallow_machine", "spray"]),
    "cow_purpose": ("text", "Why the farmer keeps cows (e.g. milk, fattening). Only for cow portfolios.", None),
    "cow_breed": ("text", "Breed of the cows being reared. Only for cow portfolios.", None),
    "type_of_breed_reared": ("text", "Type of breed reared (e.g. local, cross). Only for cow portfolios.", None),
    "has_cowshed": ("enum", "Whether the farmer has a cowshed (yes/no).", ["yes", "no"]),
    "cowshed_material": ("text", "Material of the cowshed.", None),
    "cowshed_facility": ("text", "Facilities in the cowshed (floor, drainage, light, etc.).", None),
    "cowshed_capacity": ("number", "How many cows the shed can hold.", None),
    "cow_transactional_data": ("number", "How many cow buy/sell cycles the farmer described (1 or 2).", None),
    "other_farming_activity": ("multi", "Other crops the farmer grows besides the loan crop.", ["maize", "potato", "paddy", "onion", "chili", "mustard", "vegetable", "others"]),
    "vegetable_name": ("text", "Name(s) of vegetables grown.", None),
    "others_farming": ("text", "Name of any other crop grown that is not listed.", None),
    "other_farming_activities_livestock": ("multi", "Other livestock activities (say 'none' if the farmer has none).", ["cow", "goat", "duck", "poultry", "fisheries", "others", "none"]),
    "others_livestock": ("text", "Name of any other livestock activity not listed.", None),
    "current_loan_count": ("number", "Number of loans the farmer currently has running (0 if none).", None),
    "current_loan_amount": ("number", "Amount of the farmer's current loan, BDT.", None),
    "current_loan_duration": ("number", "Duration of the farmer's current loan, months.", None),
    "installment_type": ("enum", "Installment frequency of the farmer's current loan.", ["weekly", "monthly"]),
    "weekly": ("number", "Weekly installment amount, BDT.", None),
    "monthly": ("number", "Monthly installment amount, BDT.", None),
    "remaining_month": ("number", "Months remaining on the farmer's current loan.", None),
    "loan_reason": ("text", "What the farmer's current loan was taken for (e.g. agriculture, livestock, business).", None),
    "loan_access": ("enum", "Source of the farmer's current loan.", ["bank", "mfi"]),
    "loan_access_bank": ("text", "Bank name for the farmer's current loan.", None),
    "others_bank_name": ("text", "Bank name if it is not a well-known one.", None),
    "loan_access_mfi": ("text", "MFI/NGO name for the farmer's current loan.", None),
    "others_mfi_name": ("text", "MFI/NGO name if it is not a well-known one.", None),
    "number_of_dependents": ("number", "Number of people dependent on the farmer.", None),
    "individual_income_sources": ("multi", "The farmer's own income sources.", INCOME_SOURCES),
    "income_from_agriculture": ("number", "Farmer's yearly income from agriculture, BDT.", None),
    "income_from_business": ("number", "Farmer's yearly income from business, BDT.", None),
    "business_type": ("text", "Type of the farmer's business (e.g. shop).", None),
    "income_from_labor": ("number", "Farmer's yearly income from labor, BDT.", None),
    "labor_job_details": ("text", "Details of the farmer's labor work.", None),
    "income_from_govt_job": ("number", "Farmer's yearly income from a government job, BDT.", None),
    "govt_job_details": ("text", "Details of the farmer's government job.", None),
    "income_from_private_job": ("number", "Farmer's yearly income from a private job, BDT.", None),
    "private_job_details": ("text", "Details of the farmer's private job.", None),
    "income_from_driving": ("number", "Farmer's yearly income from driving, BDT.", None),
    "income_from_stipend": ("number", "Farmer's yearly income from stipend, BDT.", None),
    "income_from_others": ("number", "Farmer's yearly income from other sources, BDT.", None),
    "family_member_income_sources": ("multi", "Income sources of other family members (say 'none' if nobody else earns).", INCOME_SOURCES + ["none"]),
    "family_member_income_from_agriculture": ("number", "Other family members' yearly income from agriculture, BDT.", None),
    "family_member_income_from_business": ("number", "Other family members' yearly income from business, BDT.", None),
    "family_member_income_from_labor": ("number", "Other family members' yearly income from labor, BDT.", None),
    "family_member_labor_details": ("text", "Details of family members' labor work.", None),
    "family_member_income_from_govt_job": ("number", "Other family members' yearly income from a government job, BDT.", None),
    "family_member_govt_job_details": ("text", "Details of family members' government jobs.", None),
    "family_member_income_from_private_job": ("number", "Other family members' yearly income from a private job, BDT.", None),
    "family_member_private_job_details": ("text", "Details of family members' private jobs.", None),
    "family_member_income_from_driving": ("number", "Other family members' yearly income from driving, BDT.", None),
    "family_member_income_from_stipend": ("number", "Other family members' yearly income from stipend, BDT.", None),
    "support_amount_from_family": ("number", "Yearly financial support received from family members living elsewhere, BDT.", None),
    "family_member_income_from_others": ("number", "Other family members' yearly income from other sources, BDT.", None),
    "monthly_expenses": ("number", "Household monthly expenses, BDT.", None),
    "how_do_you_know_the_mf": ("text", "How the farmer knows the market facilitator (MF), in romanized Bangla like the CEX agents write it.", None),
    "relation_with_mf": ("text", "Farmer's relationship with the MF ('N/A' if none).", None),
    "loan_purpose": ("text", "What the farmer will use the new iFarmer loan for.", None),
    "portfolio_name_crops": ("text", "Crop the loan is for, if discussed.", None),
    "portfolio_name_livestock": ("text", "Livestock the loan is for, if discussed.", None),
    "portfolio_name_vegetable": ("text", "Vegetable the loan is for, if discussed.", None),
    "portfolio_name_fish": ("text", "Fish the loan is for, if discussed.", None),
    "portfolio_name_fruits": ("text", "Fruit the loan is for, if discussed.", None),
    "cow_rearing_experiance": ("number", "Years of experience rearing cows.", None),
    "others_crop_harvest_month": ("text", "Harvest month(s) of other crops, as stated.", None),
    "other_answers": ("text", "Anything important the farmer said that has no field above, in romanized Bangla.", None),
}


def crop_block(prefix: str, label: str) -> dict:
    return {
        f"{prefix}_land_size": ("number", f"Land used for {label}, in decimals.", None),
        f"{prefix}_invest": ("number", f"Total cost invested in {label}, BDT.", None),
        f"{prefix}_yield": ("number", f"Total {label} production, in kg. If the farmer speaks in maund (mon), convert at 1 maund = 40 kg.", None),
        f"{prefix}_unit_price": ("number", f"Selling price of {label} per maund, BDT.", None),
    }


for c in CROPS:
    SPECS.update(crop_block(c, c))
    SPECS[f"{c}_season"] = ("text", f"Season in which {c} is grown, as stated.", None)
    SPECS[f"{c}_harvest_month"] = ("text", f"Month(s) in which {c} is harvested, as stated.", None)
SPECS.update(crop_block("vegetable", "vegetables"))
SPECS.update(crop_block("others", "the other crop"))

for a in LIVESTOCK:
    SPECS[f"{a}_invest"] = ("number", f"Cost invested in {a} rearing, BDT.", None)
    SPECS[f"{a}_sell"] = ("number", f"Sales/income from {a}, BDT.", None)
SPECS["others_livestock_invest"] = ("number", "Cost invested in the other livestock, BDT.", None)
SPECS["others_livestock_sell"] = ("number", "Sales/income from the other livestock, BDT.", None)

for n in (1, 2):
    SPECS[f"if_{n}_breed"] = ("text", f"Breed of cow/animal in transaction {n}.", None)
    SPECS[f"if_{n}_purchase_price"] = ("number", f"Purchase price in transaction {n}, BDT (0 if raised at home).", None)
    SPECS[f"if_{n}_duration"] = ("number", f"Rearing duration in transaction {n}, months.", None)
    SPECS[f"if_{n}_rearing_cost"] = ("number", f"Rearing cost in transaction {n}, BDT.", None)
    SPECS[f"if_{n}_sell"] = ("number", f"Selling price in transaction {n}, BDT.", None)

# spouse loan block mirrors the farmer's own loan block
for own_name, spouse_name in {
    "current_loan_count": "current_spouse_loan_count",
    "current_loan_amount": "current_spouse_loan_amount",
    "current_loan_duration": "current_spouse_loan_duration",
    "installment_type": "spouse_loan_installment_type",
    "weekly": "spouse_loan_weekly",
    "monthly": "spouse_loan_monthly",
    "remaining_month": "spouse_remaining_month",
    "loan_reason": "spouse_loan_reason",
    "loan_access": "spouse_loan_access",
    "loan_access_bank": "spouse_loan_access_bank",
    "others_bank_name": "spouse_loan_access_bank_others_name",
    "loan_access_mfi": "spouse_loan_access_mfi",
    "others_mfi_name": "spouse_loan_access_mfi_others_name",
}.items():
    t, d, k = SPECS[own_name]
    SPECS[spouse_name] = (t, d.replace("farmer's", "spouse's").replace("The farmer's", "The spouse's"), k)
SPECS["current_spouse_loan_count"] = ("number", "Number of loans the farmer's spouse currently has running (0 if none).", None)

# Call-system / app columns: not in the audio. Filled from manifest.csv (or the filename for a few).
MANIFEST_COLS = set()


def main(header_csv: str, out_yaml: str) -> None:
    header = next(csv.reader(open(header_csv, encoding="utf-8-sig")))
    notes_idx = header.index("Notes")
    call_form_idx = header.index("call_form")
    first_audio = header.index("current_landsize")
    fields = []
    missing = []
    for i, name in enumerate(header):
        if i < notes_idx or call_form_idx <= i < first_audio:
            fields.append({"name": name, "source": "manifest", "type": "text",
                           "description": "Call-system/loan-app value; supplied through manifest.csv, not from the audio."})
            continue
        if name not in SPECS:
            missing.append(name)
            continue
        t, d, known = SPECS[name]
        f = {"name": name, "source": "audio", "type": t, "description": d}
        if known:
            f["known_values"] = known
        fields.append(f)
    if missing:
        sys.exit(f"No spec for: {missing}")
    # extra output column that is not in the original CEX form
    fields.append({"name": "eng_notes", "source": "audio", "type": "text",
                   "description": "Same summary as Notes, written in plain English."})
    doc = {"version": 1, "closed_enums": False, "fields": fields}
    Path(out_yaml).write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"wrote {out_yaml}: {len(fields)} fields, {sum(f['source'] == 'audio' for f in fields)} from audio")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
