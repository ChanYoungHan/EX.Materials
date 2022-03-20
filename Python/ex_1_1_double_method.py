import collections

Card = collections.namedtuple("Card", ["rank", "suit"])


class FrenchDeck:
    ranks = [str(n) for n in range(2, 11)] + list("JQKA")
    suits = "spades diamonds clubs hearts".split()

    def __init__(self) -> None:
        self._cards = [Card(rank, suit) for suit in self.suits for rank in self.ranks]

    def __len__(self):
        return len(self._cards)

    def __getitem__(self, position):
        return self._cards[position]


if __name__ == "__main__":
    test_card = Card("7", "diamonds")
    print(test_card, type(test_card))

    deck = FrenchDeck()
    print(len(deck), deck[0], deck[-1])

    from random import choice

    print(choice(deck))
    print(choice(deck))
    print(choice(deck))

    suit_values = dict(spades=3, hearts=2, diamonds=1, clubs=0)

    def spades_high(card: Card):
        rank_value = FrenchDeck.ranks.index(card.rank)
        return rank_value * len(suit_values) + suit_values[card.suit]

    for card in sorted(deck, key=spades_high):
        print(card)
