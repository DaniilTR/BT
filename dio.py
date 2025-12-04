import itertools

# Исходный шифртекст (5 строк по 5 символов)
ciphertext = [
    "ОПЧУЛ",
    "С_БОО", 
    "НЕВ_О",
    "ЖАЕОН",
    "ЕЩЕИН"
]

# Функция для применения перестановки столбцов
def apply_column_permutation(matrix, perm):
    new_matrix = []
    for row in matrix:
        new_row = [row[i] for i in perm]
        new_matrix.append(''.join(new_row))
    return new_matrix

# Функция для проверки, выглядит ли текст как русский
def looks_like_russian(text):
    # Проверяем наличие русских гласных в каждой строке
    vowels = 'АЕИОУЫЭЮЯ_'
    for row in text:
        has_vowel = any(char in vowels for char in row)
        if not has_vowel:
            return False
    
    # Проверяем наличие пробелов в разумных местах
    full_text = ''.join(text)
    if full_text.count('_') > 5:  # Слишком много пробелов
        return False
        
    return True

# Генерируем все перестановки столбцов (0,1,2,3,4)
all_permutations = list(itertools.permutations([0, 1, 2, 3, 4]))

print("Перебор всех перестановок столбцов (всего 120 вариантов):\n")

for i, perm in enumerate(all_permutations, 1):
    result = apply_column_permutation(ciphertext, perm)
    
    # Выводим только результаты, которые выглядят осмысленно
    if looks_like_russian(result):
        print(f"Вариант {i}, перестановка {perm}:")
        for row in result:
            print(row)
        print(f"Текст: {''.join(result)}")
        print("-" * 50)

print("\nВсего вариантов проверено: 120")