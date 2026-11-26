"""User profile formatting utilities."""

import logging

from app.core.config import settings
from app.schemas.user import UserProfile

logger = logging.getLogger(__name__)

# --- Prompt Cache ---
_PROMPT_CACHE: dict[str, str] = {}


def _load_prompts() -> dict[str, str]:
    """Load and cache prompt templates."""
    global _PROMPT_CACHE
    if not _PROMPT_CACHE:
        _PROMPT_CACHE["system"] = settings.PROMPTS_DIR.joinpath("system.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["holland"] = settings.PROMPTS_DIR.joinpath("holland.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["user_profile"] = settings.PROMPTS_DIR.joinpath("user_profile.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["search_tool"] = settings.PROMPTS_DIR.joinpath("search_tool.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["guardrail"] = settings.PROMPTS_DIR.joinpath("guardrail.md").read_text(encoding="utf-8")
    return _PROMPT_CACHE


def build_user_profile_str(profile: UserProfile) -> str:
    """Build user profile string from template for Form Tư Vấn Hướng Nghiệp structure."""
    prompts = _load_prompts()
    template = prompts["user_profile"]

    hobbies = "N/A"
    strengths = "N/A"
    favorite_subjects = "N/A"
    experience = "N/A"
    has_chosen = "Chưa"
    career = "N/A"
    target_schools = "N/A"
    important_factors = "N/A"
    father_job = "N/A"
    mother_job = "N/A"
    family_expectations = "N/A"
    guidance_content = "N/A"

    if profile.self_understanding:
        if profile.self_understanding.hobbies:
            hobbies = ", ".join([h.name for h in profile.self_understanding.hobbies])
        if profile.self_understanding.strengths:
            strengths = ", ".join(profile.self_understanding.strengths)
        if profile.self_understanding.favorite_subjects:
            favorite_subjects = ", ".join([s.name for s in profile.self_understanding.favorite_subjects])
        experience = profile.self_understanding.experience or "N/A"

    if profile.career_orientation:
        has_chosen = "Rồi" if profile.career_orientation.has_chosen else "Chưa"
        career = profile.career_orientation.chosen_career or profile.career_orientation.considering_careers or "N/A"
        if profile.career_orientation.target_schools:
            target_schools = ", ".join(profile.career_orientation.target_schools)
        if profile.career_orientation.important_factors:
            important_factors = ", ".join(profile.career_orientation.important_factors)

    if profile.family_info:
        father_job = profile.family_info.father_job or "N/A"
        mother_job = profile.family_info.mother_job or "N/A"
        family_expectations = profile.family_info.family_expectations or "N/A"
        guidance_content = profile.family_info.guidance_content or "N/A"

    return template.format(
        full_name=profile.basic_info.full_name if profile.basic_info else "N/A",
        age=profile.basic_info.age if profile.basic_info and profile.basic_info.age else "N/A",
        address=profile.basic_info.address if profile.basic_info and profile.basic_info.address else "N/A",
        status=profile.basic_info.status if profile.basic_info and profile.basic_info.status else "N/A",
        hobbies=hobbies,
        strengths=strengths,
        favorite_subjects=favorite_subjects,
        experience=experience,
        has_chosen=has_chosen,
        career=career,
        target_schools=target_schools,
        important_factors=important_factors,
        father_job=father_job,
        mother_job=mother_job,
        family_expectations=family_expectations,
        guidance_content=guidance_content
    )
