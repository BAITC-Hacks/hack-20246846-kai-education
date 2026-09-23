export const fields = [
  ['title', 'Название задачи', 'Короткое и понятное название'],
  ['context', 'Контекст бизнеса', 'Что происходит сейчас?'],
  ['need', 'Потребность', 'Какую проблему нужно решить?'],
  ['users', 'Пользователи', 'Кто будет пользоваться решением?'],
  ['data_and_materials', 'Данные и материалы', 'Какие данные доступны команде?'],
  ['constraints', 'Ограничения', 'Сроки, технологии, конфиденциальность'],
  ['expected_result', 'Ожидаемый результат', 'Что команда должна подготовить?'],
  ['success_criteria', 'Критерии успеха', 'Как проверить результат?'],
  ['contact', 'Контакт бизнеса', 'Как связаться с представителем бизнеса?'],
  ['interaction_format', 'Взаимодействие с командой', 'Как и когда вы готовы общаться с командой?'],
  ['industry', 'Отрасль', 'Например: Розничная торговля'],
]
export const labels = Object.fromEntries(fields.map(([key, label]) => [key, label]))
export const criterionLabels = {
  context_and_need: 'Контекст и потребность', data_and_materials: 'Данные и материалы',
  expected_result: 'Ожидаемый результат', success_criteria: 'Критерии успеха',
  constraints: 'Ограничения', users: 'Пользователи', business_contact_interaction: 'Взаимодействие',
}
export const cardFields = (card = {}) => Object.fromEntries(fields.map(([key]) => [key, card[key] || '']))
export const levels = ['Draft', 'Working', 'Ready', 'Priority']
