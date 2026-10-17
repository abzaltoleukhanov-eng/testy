# Независимый аудит утверждений

Автор не проверяет сам себя. Аудитор — отдельный агент (инструмент Agent / Task, `subagent_type: general-purpose`) со свежим контекстом. Если инструмента запуска агентов нет, скажи пользователю, что содержательной проверки не было, и все утверждения останутся `NEEDS_REVIEW`.

## Что даём аудитору
- Текст утверждения, его тип и `scope_limits`.
- Для каждого цитируемого доказательства: `evidence_id`, `source_id`, ссылку и **полный сохранённый текст источника** (и родительского комментария, если есть). Не `observation` и не твои рассуждения: аудитор должен читать первоисточник.
- Список противоречащих доказательств, если есть.

Подготовить пакет: `python3 scripts/audit_packet.py --project-dir D --claims C-0003,C-0004 > packet.json`.

## Промпт аудитора (копировать как есть, подставив пакет)
```
You are an independent research auditor. You did not write these claims and you have no stake in them.
For each claim below, read ONLY the source texts provided. Decide whether the sources support the exact wording
of the claim, within its stated type and scope. Be strict about: age, gender, country, product model, purchase
motive and causality that the text does not state; a complaint presented as a purchase reason; one thread
presented as a pattern; category evidence presented as evidence about a specific product.

Return JSON only: a list, one object per claim:
{"claim_id": "...", "verdict": "SUPPORTS|PARTIAL|DOES_NOT_SUPPORT|CONTRADICTS",
 "evidence_checks": [{"evidence_id": "...", "located_span": "<exact words copied from the source text>",
                      "supports": true|false, "note": "..."}],
 "scope_issue": "<what in the claim goes beyond the sources, or empty string>",
 "open_contradiction": true|false,
 "reasoning": "<2-4 sentences>"}
Rules: located_span must be copied character for character from the source text; if nothing supports the
claim, set supports false and located_span to "". Check every evidence_id you are given.

Claims of type HYPOTHESIS or SITUATION_REACH are not judged on whether the sources prove them. Judge their
framing and add "hypothesis_check":
- "FORWARD_LOOKING_OK": the text is an untested idea, prediction or proxy, worded as such, and does not state
  as already observed any result, video content (speech, music, pacing), audience size or share, or current trend.
- "ASSERTS_UNOBSERVED_FACT": the text states something as already true or observed that the sources do not
  show (for example a percentage of a population, a ROAS result, what a video contains, "trending this week").
  Name the assertion in scope_issue.
Use verdict CONTRADICTS only if the sources contradict the idea itself.
For HYPOTHESIS / SITUATION_REACH claims also add:
- "uncovered_premises": a list of factual premises the text relies on (stated or implied, for example "there
  are no reviews online") that are NOT established by the listed premise claims ("premises" in the packet).
  A premise that only a source reported (someone said X) does not establish X itself. Do not list a premise
  that the text itself presents as an explicit condition still to be checked (for example "if weighing
  confirms X", "if X is verified", "not yet measured"): such a condition is part of what the hypothesis
  proposes to test. Empty list if none.
- "link_check": "PLAUSIBLE_UNTESTED" if the step from premises to conclusion is a reasonable idea to test,
  or "UNSUPPORTED_LEAP" if it jumps to a conclusion that ignores obvious alternative explanations.

PACKET:
<packet.json>
```

## Запись результата
Добавь к каждому объекту `"auditor": "<agent id или описание>"` и запиши: `python3 scripts/ledger.py --project-dir D add audits @audits.json`. Скрипт сам проверит, что каждый `located_span` дословно есть в тексте источника. Выдуманный аудитором фрагмент не засчитывается.

Гипотезы (`HYPOTHESIS`, классы `CAUSAL_HYPOTHESIS` и `FUTURE_HYPOTHESIS`) и охват (`SITUATION_REACH`) тоже проходят аудит: метка не обходит проверку. `ASSERTS_UNOBSERVED_FACT` даёт `BLOCKED`. Каждая фактическая посылка гипотезы должна быть отдельным утверждением со статусом `FACT_APPROVED` и стоять в `premise_claim_ids`; неодобренная посылка, непокрытая посылка, найденная аудитором, или `UNSUPPORTED_LEAP` дают `RESEARCH_QUESTION`: идея сохраняется как вопрос для проверки, но не идёт в бриф как вывод.

## Что делать с результатами
- `SUPPORTS` и `validate.py` даёт `APPROVED` → можно использовать в брифе.
- `PARTIAL` или `scope_issue` → сузь формулировку (новое утверждение) и проверь заново, либо понизь до `HYPOTHESIS`.
- `DOES_NOT_SUPPORT` → не используй; посмотри, не ошибся ли ты в интерпретации.
- `CONTRADICTS` → это находка: запиши, что опровергнуто, она может быть ценнее исходного утверждения.
- Спорные критические утверждения (центральный инсайт, причина покупки, обещание продукта) покажи пользователю с цитатами.
