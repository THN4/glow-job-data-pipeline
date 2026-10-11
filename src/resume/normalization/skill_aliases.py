"""Canonical technology names and the spellings that map to them (all aliases lowercase).

Used to normalize extracted skills and by the grounding check
(a skill counts as "found in the CV" if any alias appears).
"""

SKILL_ALIASES: dict[str, list[str]] = {
    "JavaScript": ["javascript", "js", "java script", "ecmascript", "es6"],
    "TypeScript": ["typescript", "ts"],
    "Python": ["python", "python3"],
    "Java": ["java"],
    "Kotlin": ["kotlin"],
    "Swift": ["swift"],
    "Go": ["go", "golang"],
    "Rust": ["rust"],
    "C#": ["c#", "csharp", "c sharp"],
    "C++": ["c++", "cpp"],
    "C": ["c"],
    "PHP": ["php"],
    "Ruby": ["ruby"],
    "Dart": ["dart"],
    "SQL": ["sql"],
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3"],
    "React": ["react", "reactjs", "react.js"],
    "React Native": ["react native", "react-native"],
    "Next.js": ["next.js", "nextjs", "next js"],
    "Vue.js": ["vue", "vuejs", "vue.js"],
    "Nuxt": ["nuxt", "nuxtjs", "nuxt.js"],
    "Angular": ["angular", "angularjs"],
    "Svelte": ["svelte", "sveltekit"],
    "Node.js": ["node", "nodejs", "node.js"],
    "Express": ["express", "expressjs", "express.js"],
    "NestJS": ["nestjs", "nest.js"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring Boot": ["spring boot", "springboot", "spring"],
    "Laravel": ["laravel"],
    "Flutter": ["flutter"],
    "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"],
    "Bootstrap": ["bootstrap"],
    "GraphQL": ["graphql"],
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "SQLite": ["sqlite"],
    "Firebase": ["firebase"],
    "Supabase": ["supabase"],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Azure": ["azure", "microsoft azure"],
    "Vercel": ["vercel"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "Git": ["git"],
    "GitHub Actions": ["github actions"],
    "Linux": ["linux"],
    "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch", "torch"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
}

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in SKILL_ALIASES.items():
    _ALIAS_TO_CANONICAL[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[_alias] = _canonical


def normalize_skill_name(name: str) -> str:
    """'reactjs' -> 'React'. Unknown names are returned trimmed, unchanged."""
    trimmed = " ".join(name.split())
    return _ALIAS_TO_CANONICAL.get(trimmed.lower(), trimmed)


def skill_spellings(name: str) -> list[str]:
    """All lowercase spellings that count as the given skill (including itself)."""
    canonical = normalize_skill_name(name)
    spellings = [canonical.lower(), name.strip().lower(), *SKILL_ALIASES.get(canonical, [])]
    return list(dict.fromkeys(spellings))
