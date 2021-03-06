import torch, os
import numpy as np
from dataloaders.miniImageNet import MiniImageNet, FewShotDataloader
import scipy.stats

from utilities import setup_seed

import argparse
from tqdm import tqdm

from MAML.meta import Meta


def mean_confidence_interval(accs, confidence=0.95):
    n = accs.shape[0]
    m, se = np.mean(accs), scipy.stats.sem(accs)
    h = se * scipy.stats.t._ppf((1 + confidence) / 2, n - 1)
    return m, h


def main():

    torch.manual_seed(1234)
    torch.cuda.manual_seed_all(1234)
    np.random.seed(1234)
    setup_seed(1234)

    print(args)

    config = [
        ('conv2d', [64, 3, 3, 3, 1, 0]),
        ('relu', [True]),
        ('bn', [64]),
        ('max_pool2d', [2, 2, 0]),
        ('conv2d', [64, 64, 3, 3, 1, 0]),
        ('relu', [True]),
        ('bn', [64]),
        ('max_pool2d', [2, 2, 0]),
        ('conv2d', [64, 64, 3, 3, 1, 0]),
        ('relu', [True]),
        ('bn', [64]),
        ('max_pool2d', [2, 2, 0]),
        ('conv2d', [64, 64, 3, 3, 1, 0]),
        ('relu', [True]),
        ('bn', [64]),
        ('max_pool2d', [2, 1, 0]),
        ('flatten', []),
        ('linear', [args.n_way, 64 * 5 * 5])
    ]

    #device = torch.device('cuda')
    maml = Meta(args, config)

    # ------------------------------------------
    dataset_train = MiniImageNet(phase='train')
    dataset_val = MiniImageNet(phase='val')
    data_loader = FewShotDataloader

    dloader_train = data_loader(
        dataset=dataset_train,
        nKnovel=args.n_way,
        nKbase=0,
        nExemplars=args.k_spt,  # num training examples per novel category
        nTestNovel=args.n_way * args.k_spt,  # num test examples for all the novel categories
        nTestBase=0,  # num test examples for all the base categories
        batch_size=args.task_num,
        num_workers=4,
        epoch_size=args.task_num * 1000,  # num of batches per epoch
    )

    dloader_val = data_loader(
        dataset=dataset_val,
        nKnovel=args.n_way,
        nKbase=0,
        nExemplars=args.k_qry,  # num training examples per novel category
        nTestNovel=args.k_qry * args.n_way,  # num test examples for all the novel categories
        nTestBase=0,  # num test examples for all the base categories
        batch_size=1,
        num_workers=0,
        epoch_size=1000,  # num of batches per epoch
    )

    # ---------------------------------------------------

    max_val_acc = 0

    if not os.path.exists(os.path.join(args.save_path)):
        os.makedirs(os.path.join(args.save_path))

    for epoch in range(1, args.epoch+1):
        # fetch meta_batchsz num of episode each time

        train_accuracies = []

        for i, batch in enumerate(tqdm(dloader_train(epoch)), 1):

            data_support, labels_support, data_query, labels_query, _, _ = [x.cuda() for x in batch]

            data_support = data_support.float()
            data_query = data_query.float()

            labels_support = labels_support.long()
            labels_query = labels_query.long()

            #x_spt, y_spt, x_qry, y_qry = x_spt.to(device), y_spt.to(device), x_qry.to(device), y_qry.to(device)

            accs, loss_cls = maml.forward(data_support, labels_support, data_query, labels_query)

            train_accuracies.append(accs)

            if i % 100 == 0:
                avg_accs = np.array(train_accuracies).mean(axis=0).astype(np.float16)* 100
                print( 'Train Epoch: {} \tLoss_cls: {:.4f}'.format(i, loss_cls), '\ttraining acc:', avg_accs)

        # Evaluate on the validation split

        val_accuracies = []

        for i, batch in enumerate(tqdm(dloader_val(epoch)), 1):

            data_support, labels_support, data_query, labels_query, _, _ = [x.cuda() for x in batch]

            data_support = data_support.float().squeeze(0)
            data_query = data_query.float().squeeze(0)

            labels_support = labels_support.long().squeeze(0)
            labels_query = labels_query.long().squeeze(0)

            accs = maml.finetunning(data_support, labels_support, data_query, labels_query)
            val_accuracies.append(accs)

            # [b, update_step+1]
        val_acc_avg = np.array(val_accuracies).mean(axis=0).astype(np.float16)[-1]*100

        maml.load_selfvars(data_support)

        if val_acc_avg > max_val_acc:
            max_val_acc = val_acc_avg


            state = {'epoch': epoch + 1, 'model': maml.net.state_dict(),
                     'optimizer': maml.meta_optim.state_dict()}
            torch.save(state
                       , os.path.join(args.save_path, 'best_model.pth.tar'.format(epoch)))

            print( 'Validation Epoch: {}\t\t\tAccuracy: {:.2f}  % (Best)' \
                .format(epoch, val_acc_avg))
        else:
            print( 'Validation Epoch: {}\t\t\tAccuracy: {:.2f} %' \
                .format(epoch, val_acc_avg))

        if epoch % 2 == 0:
            state = {'epoch': epoch + 1, 'model': maml.net.state_dict(),
                     'optimizer': maml.meta_optim.state_dict()}
            torch.save(state
                       , os.path.join(args.save_path, 'epoch_{}.pth.tar'.format(epoch)))




if __name__ == '__main__':
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    argparser = argparse.ArgumentParser()
    argparser.add_argument('--epoch', type=int, help='epoch number', default=60)
    argparser.add_argument('--n_way', type=int, help='n way', default=5)
    argparser.add_argument('--k_spt', type=int, help='k shot for support set', default=5)
    argparser.add_argument('--k_qry', type=int, help='k shot for query set', default=10)
    argparser.add_argument('--imgsz', type=int, help='imgsz', default=84)
    argparser.add_argument('--imgc', type=int, help='imgc', default=3)
    argparser.add_argument('--task_num', type=int, help='meta batch size, namely task num', default=4)
    argparser.add_argument('--meta_lr', type=float, help='meta-level outer learning rate', default=1e-3)
    argparser.add_argument('--update_lr', type=float, help='task-level inner update learning rate', default=0.01)
    argparser.add_argument('--update_step', type=int, help='task-level inner update steps', default=5)
    argparser.add_argument('--update_step_test', type=int, help='update steps for finetunning', default=10)
    argparser.add_argument('--save_path', type=str, help='model save path', default='/data/save_models/..')

    args = argparser.parse_args()

    main()
