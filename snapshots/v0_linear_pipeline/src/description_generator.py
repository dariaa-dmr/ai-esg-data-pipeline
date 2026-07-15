"""
Генератор описания компании по инструкции v5.2.
Использует данные из Dadata и исходное описание (если есть).
"""
import re

def generate_company_description(row: dict) -> tuple[str, str, str]:
    """
    Возвращает (CompanyDescription, CompanyEmployees, CompanyRevenue)
    row содержит поля: INN, CompanyNameOfficial, Address_dadata, OKVED_dadata,
    Description (исходное), Sector, Industry, Subindustry и т.д.
    """
    # Попробуем извлечь численность и выручку из исходного описания (если есть)
    desc = row.get('Description', '')
    employees = ''
    revenue = ''
    if desc:
        # Ищем численность
        emp_match = re.search(r'(?:численность|среднесписочная численность)\s+работников\s+[—–-]?\s*(?:около\s*)?(\d[\d\s]*)(?:\s*(?:тыс\.|тысяч)?)\s*(?:человек|чел\.?)', desc, re.IGNORECASE)
        if emp_match:
            employees = emp_match.group(1).replace(' ', '')
        else:
            emp_match2 = re.search(r'около\s+(\d[\d\s]*)\s+человек', desc, re.IGNORECASE)
            if emp_match2:
                employees = emp_match2.group(1).replace(' ', '')
        # Ищем выручку
        rev_match = re.search(r'(?:выручка|годовая выручка)\s+[—–-]?\s*(?:около\s*)?(\d[\d\s]*)\s*(?:млрд\s*руб|млрд\s*р\.?)', desc, re.IGNORECASE)
        if rev_match:
            revenue = rev_match.group(1).replace(' ', '')
        else:
            rev_match2 = re.search(r'около\s+(\d[\d\s]*)\s+млрд\s*руб', desc, re.IGNORECASE)
            if rev_match2:
                revenue = rev_match2.group(1).replace(' ', '')
    # Если не нашли, оставляем пустыми

    # Теперь строим само описание
    official_name = row.get('CompanyNameOfficial', '')
    address = row.get('Address_dadata', '')
    okved = row.get('OKVED_dadata', '')
    industry = row.get('Industry', '')
    subindustry = row.get('Subindustry', '')

    # Определяем год (если есть в исходном описании, иначе неизвестен)
    year_match = re.search(r'\b(19|20)\d{2}\b', desc) if desc else None
    year = year_match.group(0) if year_match else 'неизвестном году'

    # Определяем город из адреса
    city = ''
    if address:
        parts = address.split(',')
        for p in parts:
            if 'г ' in p or 'г.' in p:
                city = p.strip()
                break
        if not city:
            city = parts[0] if parts else ''

    # Определяем регионы
    region = ''
    if address:
        # Ищем субъект РФ
        for pattern in [
            r'(Республика\s+\S+)',
            r'([А-ЯЁа-яё\- ]+\s+(?:область|обл\.))',
            r'([А-ЯЁа-яё\- ]+\s+край)',
            r'(г\.\s*(?:Москва|Санкт-Петербург|Севастополь))',
            r'([А-ЯЁа-яё\- ]+\s+(?:автономный округ|АО))'
        ]:
            m = re.search(pattern, address, re.IGNORECASE)
            if m:
                region = m.group(1).strip()
                break
        if not region:
            region = city

    # Строим предложения
    sent1 = f"{official_name} основано в {year} в {city} и занимается"
    if desc:
        first_sent = desc.split('.')[0]
        sent1 += f" {first_sent.lower()}."
    else:
        sent1 += f" деятельностью в сфере {industry} (подотрасль: {subindustry})."

    sent2 = f"Компания обслуживает {region}. Основная база находится в {city}."

    if desc:
        sentences = desc.split('.')
        if len(sentences) >= 3:
            key_fact = sentences[2].strip()
        else:
            key_fact = sentences[-1].strip() if sentences else ''
    else:
        key_fact = f"Основной вид деятельности по ОКВЭД: {okved}."

    if not key_fact:
        key_fact = "Компания играет важную роль в инфраструктуре региона."

    sent3 = key_fact

    if not employees:
        employees = 'неизвестна'
    if not revenue:
        revenue = 'неизвестна'

    if 'ГБУ' in official_name or 'МБУ' in official_name or 'БУ' in official_name or 'ГУП' in official_name or 'МУП' in official_name:
        sent4 = f"Численность работников — около {employees} человек, годовой бюджет — около {revenue} руб."
    else:
        sent4 = f"Численность работников — около {employees} человек, годовая выручка — около {revenue} руб."

    description = f"{sent1} {sent2} {sent3} {sent4}"
    description = re.sub(r'\s+', ' ', description).strip()

    return description, employees, revenue