"""
Document domain classifier.

Classifies documents into knowledge domains for intelligent retrieval grouping.

Strategy:
  1. Rule-based classification from document filename (fast, free)
  2. AI-based classification using first few content chunks (accurate, needs API key)
  3. Fallback: cleaned filename stem as domain name
"""
import re
import logging

logger = logging.getLogger(__name__)

# ── Rule-based patterns ───────────────────────────────────────────────────────
# Each entry: (compiled_regex, domain_name)  — matched against filename (no ext)

_RULES: list[tuple] = []


def _r(pattern: str, domain: str) -> None:
    _RULES.append((re.compile(pattern, re.IGNORECASE), domain))


# ── Programming languages ─────────────────────────────────────────────────────
_r(r'\bjava\b(?!\s*script)',           "Java Programming")
_r(r'\bpython\b|\bdjango\b|\bflask\b|\bfastapi\b|\bpandas\b|\bnumpy\b|\bscipy\b', "Python Programming")
_r(r'\bc\s+programming\b|\bc\s+language\b|\bc\s+basics\b|\bc\s+fundament|\bc\s+code', "C Programming")
_r(r'\bc\+\+\b|\bcpp\b|\bcplusplus\b', "C++ Programming")
_r(r'\bjavascript\b|\bnode\.?js\b|\bnodejs\b|\breact\.?js\b|\bvue\.?js\b|\bangular\b|\bnext\.?js\b', "JavaScript Programming")
_r(r'\btypescript\b',                  "TypeScript Programming")
_r(r'\bkotlin\b',                      "Kotlin Programming")
_r(r'\bswift\b|\bios\s+dev\b|\bxcode\b', "iOS Development")
_r(r'\brust\b(?!y|\s+belt)',           "Rust Programming")
_r(r'\bgolang\b|\bgo\s+lang|\bgo\s+programming\b|\bgo\s+language\b', "Go Programming")
_r(r'\bruby\b|\brails\b',              "Ruby Programming")
_r(r'\bphp\b',                         "PHP Programming")
_r(r'\br\s+programming\b|\br\s+language\b|\bggplot\b|\bdplyr\b', "R Programming")
_r(r'\bscala\b',                       "Scala Programming")
_r(r'\bhaskell\b',                     "Haskell Programming")
_r(r'\bc#\b|\bcsharp\b|\b\.net\b|\basp\.net\b', "C# & .NET")
_r(r'\bassembly\b|\basm\b',            "Assembly Programming")
_r(r'\bperl\b',                        "Perl Programming")
_r(r'\blua\b',                         "Lua Programming")
_r(r'\bmatlab\b',                      "MATLAB")
_r(r'\bdart\b|\bflutter\b',           "Flutter & Dart")
_r(r'\bandroid\b',                     "Android Development")

# ── Data & AI ─────────────────────────────────────────────────────────────────
_r(r'\bmachine\s*learning\b|\bdeep\s*learning\b|\bneural\s*net|\bai\s+model', "Machine Learning & AI")
_r(r'\bdata\s*science\b|\bdata\s*analysis\b|\bdata\s*analytics\b', "Data Science")
_r(r'\bstatistic\b|\bprobability\b|\bbiostatistic\b', "Statistics & Probability")
_r(r'\bcomputer\s*vision\b|\bimage\s*process|\bopencv\b', "Computer Vision")
_r(r'\bnatural\s*language\b|\bnlp\b|\btext\s*mining\b|\bsentiment', "NLP & Text Mining")
_r(r'\bdata\s*engineer\b|\betl\b|\bairflow\b|\bspark\b|\bhadoop\b', "Data Engineering")
_r(r'\bbig\s*data\b',                  "Big Data")

# ── Databases ─────────────────────────────────────────────────────────────────
_r(r'\bsql\b|\bmysql\b|\bpostgresql\b|\boracle\s+db|\bsqlite\b|\bdatabase\b|\bdbms\b', "Database & SQL")
_r(r'\bmongodb\b|\bnosql\b|\bfirebase\b|\bdynamodb\b|\bcassandra\b', "NoSQL Databases")
_r(r'\bredis\b|\bmemcached\b|\bcaching\b', "Caching & Redis")

# ── Web & Frontend ────────────────────────────────────────────────────────────
_r(r'\bhtml\b|\bcss\b|\bweb\s*design\b|\bbootstrap\b|\btailwind\b', "Web Development")
_r(r'\bfrontend\b|\bfront[- ]end\b|\bui\s+design\b|\bux\b|\bfigma\b', "Frontend & UI/UX")
_r(r'\brest\s*api\b|\bgraphql\b|\bapi\s*design\b|\bbackend\b|\bweb\s*api\b', "Backend Development")
_r(r'\bmicroservice\b|\bsoa\b|\bdistributed\s+system', "Software Architecture")

# ── DevOps & Cloud ─────────────────────────────────────────────────────────────
_r(r'\bdocker\b|\bkubernetes\b|\bk8s\b|\bcontainer\b', "DevOps & Containers")
_r(r'\baws\b|\bazure\b|\bgcp\b|\bcloud\s+computing\b|\bcloud\s+platform', "Cloud Computing")
_r(r'\bci[\s/]?cd\b|\bjenkins\b|\bgithub\s*actions\b|\bdevops\b|\bgitlab\b', "DevOps & CI/CD")
_r(r'\blinux\b|\bunix\b|\bbash\b|\bshell\s*script\b', "Linux & Shell Scripting")
_r(r'\bnetwork\b|\btcp\b|\bip\b|\bdns\b|\bfirewall\b', "Networking")

# ── Security ──────────────────────────────────────────────────────────────────
_r(r'\bcybersecurity\b|\binformation\s+security\b|\binfosec\b', "Cybersecurity")
_r(r'\bethical\s*hack|\bpenetration\s*test|\bpen\s*test\b|\bkali\b', "Ethical Hacking")
_r(r'\bencryption\b|\bcryptograph\b',  "Cryptography")

# ── Business & Management ─────────────────────────────────────────────────────
_r(r'\bfinance\b|\bfinancial\b|\baccounting\b|\bbudget\b|\binvestment\b|\bbanking\b', "Finance & Accounting")
_r(r'\bmarketing\b|\bsales\b|\bcrm\b|\bdigital\s+marketing\b|\bbrand\b', "Marketing & Sales")
_r(r'\bhuman\s*resources\b|\bhr\s+policy|\bhr\s+manual|\bemployee\b|\bpayroll\b|\brecruitment\b', "Human Resources")
_r(r'\blegal\b|\bcontract\b|\bcompliance\b|\bregulation\b|\blaw\b', "Legal & Compliance")
_r(r'\bproject\s*management\b|\bagile\b|\bscrum\b|\bkanban\b|\bpmp\b|\bpmi\b', "Project Management")
_r(r'\bbusiness\s*analysis\b|\bba\s+document\b', "Business Analysis")
_r(r'\boperations\b|\bsupply\s*chain\b|\blogistic\b', "Operations & Logistics")

# ── Science & Math ────────────────────────────────────────────────────────────
_r(r'\bphysics\b',                     "Physics")
_r(r'\bchemistry\b',                   "Chemistry")
_r(r'\bbiology\b|\bbiotechnology\b',   "Biology & Biotechnology")
_r(r'\bmathematics\b|\bmaths?\b|\bcalculus\b|\balgebra\b|\bgeometry\b|\bdiscrete\s+math', "Mathematics")

# ── Computer Science Fundamentals ─────────────────────────────────────────────
_r(r'\bdata\s*structure\b|\balgorithm\b', "Data Structures & Algorithms")
_r(r'\boperating\s*system\b|\bos\s+concept\b', "Operating Systems")
_r(r'\bcomputer\s*(network|architecture|organization|science)', "Computer Science")
_r(r'\bcompiler\b|\bprogramming\s*language\s*theory\b', "Compiler Design")
_r(r'\bsoftware\s*engineer\b|\bsoftware\s*design\b|\bdesign\s*pattern\b', "Software Engineering")
_r(r'\bobject[\s-]oriented\b|\boop\b',  "Object-Oriented Programming")


def classify_domain_from_name(filename: str) -> str | None:
    """Rule-based classification from filename. Returns None if no rule matches."""
    name = re.sub(r'\.[^.]+$', '', filename)  # strip extension
    for pattern, domain in _RULES:
        if pattern.search(name):
            return domain
    return None


_AI_PROMPT = (
    "You are a document classifier. Given a document name and a content sample, "
    "output ONLY the knowledge domain name (2–5 words, title case).\n"
    "Rules:\n"
    "• For programming documents always include the language: 'Java Programming', "
    "'Python Programming', 'C Programming', 'JavaScript Programming', etc.\n"
    "• For business docs use: 'Finance & Accounting', 'Human Resources', "
    "'Project Management', 'Marketing & Sales', etc.\n"
    "• Do NOT include words like Tutorial, Basics, Guide, Fundamentals in the domain.\n"
    "• Output ONLY the domain name. No explanation. No punctuation at the end."
)


async def classify_domain_with_ai(doc_name: str, content_sample: str) -> str | None:
    """AI-based classification using document name + content sample."""
    try:
        from app.ai_providers import get_ai_provider
        provider = get_ai_provider()
        if not getattr(provider, "is_configured", False):
            return None

        question = (
            f'Document name: "{doc_name}"\n\n'
            f'Content sample:\n{content_sample[:2500]}\n\n'
            f'What is the knowledge domain of this document?'
        )
        full_text = ""
        async for token in provider.stream_chat(
            system_prompt=_AI_PROMPT,
            question=question,
            context="",
            conversation_history=None,
        ):
            full_text += token
            if len(full_text) > 120:
                break

        domain = full_text.strip().strip(".,;:\"'")
        if domain and 3 <= len(domain) <= 60:
            logger.info(f"[Domain] AI classified '{doc_name}' → '{domain}'")
            return domain
    except Exception as exc:
        logger.warning(f"[Domain] AI classification failed for '{doc_name}': {exc}")
    return None


async def classify_document_domain(doc_name: str, chunks: list) -> str:
    """
    Classify a document into a knowledge domain.

    Returns a non-empty domain name string. Never raises.

    Strategy:
      1. Rule-based from filename
      2. AI from content sample
      3. Fallback: cleaned filename stem
    """
    # 1. Rule-based (fast path)
    domain = classify_domain_from_name(doc_name)
    if domain:
        logger.info(f"[Domain] Rule-based: '{doc_name}' → '{domain}'")
        return domain

    # 2. AI-based (accurate, requires API key)
    content_sample = "\n\n".join(
        getattr(c, "text", str(c))
        for c in (chunks or [])[:4]
    ).strip()
    if content_sample:
        domain = await classify_domain_with_ai(doc_name, content_sample)
        if domain:
            return domain

    # 3. Fallback: derive from filename
    stem = re.sub(r'\.[^.]+$', '', doc_name)
    stem = re.sub(r'[-_]+', ' ', stem)
    stem = re.sub(r'\s+', ' ', stem).strip().title()
    domain = stem[:100] if stem else "General"
    logger.info(f"[Domain] Filename fallback: '{doc_name}' → '{domain}'")
    return domain
