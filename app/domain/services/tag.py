from typing import Protocol

from app.domain.entities import Tag


class TagRepository(Protocol):
    def get_tree(self) -> list[Tag]: ...


class TagService:
    def __init__(self, repository: TagRepository) -> None:
        self.repository = repository
        self._tree_cache: list[Tag] | None = None

    def get_tag_tree(self) -> list[Tag]:
        if self._tree_cache is None:
            self._tree_cache = self.repository.get_tree()
        return self._tree_cache
