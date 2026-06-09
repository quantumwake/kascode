import math
import sys


def is_prime(n):
    """Check if a number is prime."""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    for i in range(5, int(math.isqrt(n)) + 1, 6):
        if n % i == 0 or n % (i + 2) == 0:
            return False
    return True


def sieve_of_eratosthenes(limit):
    """Generate all primes up to limit using the Sieve of Eratosthenes."""
    if limit < 2:
        return []
    sieve = [True] * (limit + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(math.isqrt(limit)) + 1):
        if sieve[i]:
            for j in range(i * i, limit + 1, i):
                sieve[j] = False
    return [i for i, prime in enumerate(sieve) if prime]


def main():
    if len(sys.argv) > 1:
        num = int(sys.argv[1])
        primes = sieve_of_eratosthenes(num)
        print(f"Primes up to {num}:")
        print(primes)
        print(f"\nTotal: {len(primes)} primes")
    else:
        print("Check if a number is prime, or list primes up to N.")
        print()
        print("Usage:")
        print("  python prime.py <number>   -> List all primes up to <number>")
        print("  python prime.py             -> Interactive mode")
        print()

        while True:
            try:
                user_input = input("Enter a number (or 'q' to quit): ").strip()
                if user_input.lower() == 'q':
                    print("Goodbye!")
                    break
                n = int(user_input)
                if is_prime(n):
                    print(f"{n} is prime!")
                else:
                    print(f"{n} is not prime.")
            except ValueError:
                print("Please enter a valid integer.")


if __name__ == "__main__":
    main()
