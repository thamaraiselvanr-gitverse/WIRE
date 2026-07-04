from abc import ABC, abstractmethod


class StorageBackend(ABC):
    @abstractmethod
    def initialize_for_url(self, url: str) -> None:
        pass

    @abstractmethod
    def save_page(self, url: str, content: str) -> None:
        pass

    @abstractmethod
    def get_asset_path(self) -> str:
        pass
