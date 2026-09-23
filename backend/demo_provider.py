"""Local deterministic responses derived only from the submitted source text.

This adapter exercises the normal AI workflow; it does not perform LLM inference
or infer business facts. Questions identify the fields for explicit user answers.
"""
from .ai_models import AIQuestion, AnalysisOutput, Evidence, ExtractedCard
from .ai_provider import AIUnavailable


class DemoAIProvider:
    provider_name = "demo"

    # Keep this order and wording stable: the persisted question text identifies
    # the destination field, independently of the workflow's generated qN IDs.
    _prompts = (
        ("context", "Опишите текущую ситуацию и процесс бизнеса отдельным ответом: что происходит сейчас?"),
        ("need", "Какую конкретную проблему или потребность из этого черновика нужно решить?"),
        ("users", "Кто именно будет пользоваться решением этой задачи?"),
        ("data_and_materials", "Какие данные и материалы доступны для этой задачи? Если их нет, укажите это явно."),
        ("constraints", "Какие ограничения есть у этой задачи: сроки, бюджет, технологии или другие условия? Если ограничений нет, укажите это явно."),
        ("expected_result", "Какой конкретный результат должна передать команда по этой задаче?"),
        ("success_criteria", "Как вы проверите, что результат этой задачи успешен? Укажите проверяемые критерии."),
        ("contact", "Кто со стороны бизнеса отвечает за эту задачу и как с ним связаться?"),
        ("interaction_format", "Как вы будете взаимодействовать с командой по этой задаче: формат и частота связи?"),
    )

    @staticmethod
    def _known_card(draft: str) -> ExtractedCard:
        fields = {field: None for field in ExtractedCard.model_fields}
        # Drafts permit 20000 characters, but card fields permit only 10000.
        # Never cut a source sentence: truncation could change its meaning.
        if draft.strip() and len(draft) <= 10000:
            fields["context"] = Evidence(source_id="draft", quote=draft)
        return ExtractedCard(**fields)

    def _questions(self, draft: str) -> list[AIQuestion]:
        context_known = self._known_card(draft).context is not None
        # This is a labelled excerpt for the reader, never card evidence. Copying
        # it into a question does not claim to understand or extract its facts.
        excerpt = draft[:180]
        if len(draft) > 180:
            excerpt += "…"
        return [
            AIQuestion(
                field=field,
                kind="detail" if field == "context" and context_known else "missing",
                text=f"Фрагмент вашего черновика: «{excerpt}». {prompt}",
            )
            for field, prompt in self._prompts
        ]

    def analyze(self, draft: str) -> AnalysisOutput:
        return AnalysisOutput(
            known_information=self._known_card(draft),
            questions=self._questions(draft),
        )

    def propose(self, draft: str, answers: list[dict]) -> ExtractedCard:
        card = self._known_card(draft)
        fields_by_question = {question.text: question.field for question in self._questions(draft)}
        answered_fields = set()
        for answer in answers:
            field = fields_by_question.get(answer.get("question"))
            source_id, text = answer.get("source_id"), answer.get("text")
            if (field is None or field in answered_fields
                    or not isinstance(source_id, str) or not source_id.startswith("answer:")
                    or not source_id.removeprefix("answer:")
                    or not isinstance(text, str) or not text.strip() or len(text) > 10000):
                # In particular, do not reinterpret questions saved by another
                # provider after a mode switch. Reanalysis gives demo questions.
                raise AIUnavailable("invalid_output")
            answered_fields.add(field)
            # Whole answers preserve negation and uncertainty. The unchanged
            # workflow will still verify every quote against its exact source.
            setattr(card, field, Evidence(source_id=source_id, quote=text))
        return card
