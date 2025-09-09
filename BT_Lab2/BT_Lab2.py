import hashlib

def find_key(iin: str, zeros: int, ):
    key = 0
    prefix = "0" * zeros

    while True:
        text = f"{iin}+{key}"
        hash_value = hashlib.sha256(text.encode()).hexdigest()
        if hash_value.startswith(prefix):
            return key, hash_value, 

        key += 1

if __name__ == "__main__":
    iin = input("Введите ИИН: ") # Пример: 041022501645

    # 1 ноль
    k1, z1 = find_key(iin, 1)
    print(f"1 ноль -> ключ: {k1}, нулей: {z1},")

    # 2 нуля
    k2, z2 = find_key(iin, 2)
    print(f"2 нуля -> ключ: {k2}, нулей: {z2},")

    # 3 и более нулей
    k3, z3 = find_key(iin, 3)
    print(f"3 нуля -> ключ: {k3}, нулей: {z3},")
    # если необходимо другое количество нулей, можно выбрать значение использовав zeros == 4, 5, 6 и т.д.