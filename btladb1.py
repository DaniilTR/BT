def calculate_control_digit(iin_11_digits: str) -> int:
    if len(iin_11_digits) != 11 or not iin_11_digits.isdigit():
        raise ValueError("IIN должен содержать ровно 11 цифр.")
    
    digits = [int(ch) for ch in iin_11_digits]

    # Первый проход: веса от 1 до 11
    weights_pass1 = list(range(1, 12))
    s1 = sum(d * w for d, w in zip(digits, weights_pass1))
    c1 = s1 // 11
    k1 = s1 - c1 * 11

    if k1 < 10:
        return k1  # Контрольное число найдено

    # Второй проход: веса начинаются с 3
    weights_pass2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]
    s2 = sum(d * w for d, w in zip(digits, weights_pass2))
    c2 = s2 // 11
    k2 = s2 - c2 * 11

    return k2 if k2 < 10 else 0  # Если снова >=10, возвращается 0 (по стандарту РК)

# Пример использования:
iin_11 = "85080831073"
control_digit = calculate_control_digit(iin_11)
print(f"Контрольное число: {control_digit}")
