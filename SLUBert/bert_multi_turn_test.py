import os
import sys

install_path = os.path.abspath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(install_path)

import random
from typing import List, Tuple

import numpy as np
import torch
from torch import nn
from torch.optim import Adam

from model.decoder import MultiTurnDecoder
from utils.arguments import arguments
from dataset.data import BIO, Label, LabelConverter, MyDataLoader, MyDataset


def get_output(text: List[str], output: torch.Tensor, label_converter: LabelConverter) -> List[Tuple[str, str, str]]:
    ret = []
    output = output[1:-1].argmax(dim=1)
    labels = [label_converter.index_to_label(i.item()) for i in output]
    labels.append(Label(BIO.O, '', ''))
    start = -1
    act = ''
    slot = ''
    for i, v in enumerate(labels):
        if v.bio == BIO.B:
            start = i
            act = v.act
            slot = v.slot
        elif v.bio == BIO.O and start != -1:
            value = ''.join(text[start:i])
            ret.append([act, slot, value])
        elif v.bio == BIO.I and (v.act, v.slot) != (act, slot):
            # invalid tag sequence
            return []
    return ret


def set_random_seed(random_seed: int) -> None:
    random.seed(random_seed)
    torch.manual_seed(random_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(random_seed)
    np.random.seed(random_seed)


set_random_seed(arguments.seed)

label_converter = LabelConverter('data/ontology.json')
pretrained_model_name = 'bert-base-chinese'
cache_dir = 'cache'
train_dataset = MyDataset('data/train.json', label_converter, pretrained_model_name, cache_dir)
dev_dataset = MyDataset('data/development.json', label_converter, pretrained_model_name, cache_dir)
train_data_loader = MyDataLoader(train_dataset, batch_size=arguments.batch_size, shuffle=True)
dev_data_loader = MyDataLoader(dev_dataset)
encoding_len = train_dataset[0][0][0].vector_with_noise.shape[1]
decoder = MultiTurnDecoder(encoding_len, label_converter.num_indexes).to(arguments.device)
optimizer = Adam(decoder.parameters(), arguments.lr)
loss_fn = nn.CrossEntropyLoss()

for epoch in range(arguments.max_epoch):
    print('epoch:', epoch)
    total_loss = 0
    for batch_x, batch_y in train_data_loader:
        optimizer.zero_grad()
        decoder.reset()
        for round_x, round_y in zip(batch_x, batch_y):
            for x, y in zip(round_x, round_y):
                output = decoder(x.vector_without_noise)
                loss = loss_fn(output, y)
                total_loss += loss.item()
                loss.backward()
        optimizer.step()
    print('avg. loss:', total_loss / len(train_dataset))

    # test
    n_total = 0
    n_correct = 0
    with torch.no_grad():
        for batch_x, batch_y in dev_data_loader:
            for round_x, round_y in zip(batch_x, batch_y):
                for x, y in zip(round_x, round_y):
                    n_total += 1
                    output = decoder(x.vector_with_noise)
                    prediction = get_output(x.tokens_with_noise, output, label_converter)
                    expected = get_output(x.tokens_without_noise, y, label_converter)
                    if prediction == expected:
                        n_correct += 1
    print(n_correct, n_total, n_correct / n_total)
