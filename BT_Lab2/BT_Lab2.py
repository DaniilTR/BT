def find_outlier(integers):
    # Берём первые три числа
    first_three = integers[:3]

    # Считаем, сколько среди них чётных
    evens = sum(1 for num in first_three if num % 2 == 0)

    # Определяем, кто в большинстве: чётные или нечётные
    majority_is_even = evens > 1

    # Ищем число, которое не совпадает с большинством
    for num in integers:
        if (num % 2 == 0) != majority_is_even:
            return num


# Примеры использования:
print(find_outlier([2, 4, 0, 100, 4, 11, 2602, 36]))
# ➝ 11 (единственное нечётное)

print(find_outlier([160, 3, 1719, 19, 11, 13, -21]))
# ➝ 160 (единственное чётное)
